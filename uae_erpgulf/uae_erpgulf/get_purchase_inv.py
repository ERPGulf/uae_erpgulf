"""get purchase invoice"""
import frappe
import json
from frappe import _
from uae_erpgulf.uae_erpgulf.provider_settings import get_active_provider_settings
from uae_erpgulf.uae_erpgulf.providers import get_adapter, _get_registry


def _parse_with_adapter(company, invoice_json):
    """Read an incoming invoice JSON with the company's active provider's
    adapter. If that adapter can't find a supplier or lines in it (e.g. an
    older file from a different ASP), try the other registered adapters."""
    settings = get_active_provider_settings(company)
    tried = []

    def attempt(adapter):
        try:
            parsed = adapter.parse_incoming_invoice(invoice_json) or {}
        except NotImplementedError:
            return None
        if (parsed.get("supplier_name") or parsed.get("vat_number")) and parsed.get("lines"):
            return parsed
        return None

    active = get_adapter(settings)
    tried.append(active.__class__)
    parsed = attempt(active)
    if parsed:
        return parsed

    for dotted_path in _get_registry().values():
        adapter_class = frappe.get_attr(dotted_path)
        if adapter_class in tried:
            continue
        tried.append(adapter_class)
        parsed = attempt(adapter_class(settings))
        if parsed:
            return parsed

    frappe.throw(_("Could not read supplier and invoice lines from this JSON file with any provider."))


def _payment_means_option(code):
    """Bare payment means code ("1", "30") -> the matching option of the
    Purchase Invoice Payment Means Codes field ("1 - Instrument not
    defined"). Returns None if the field or a matching option doesn't exist."""
    if not code:
        return None
    field = frappe.get_meta("Purchase Invoice").get_field("custom_payment_means_codes")
    if not field:
        return None

    code = str(code).strip()
    for option in (field.options or "").split("\n"):
        option = option.strip()
        if option == code or option.split(" - ", 1)[0].strip() == code:
            return option
    return None


@frappe.whitelist()
def get_fta_incoming_invoices():
    """Fetch UAE Incoming Invoices with status Not Submitted"""
    fta_invoices = frappe.db.get_all(
        'UAE Incoming Invoices',
        filters={'status': 'Not Submitted'},
        fields=['name', 'document_id', 'incoming_invoice_file']
    )
    return fta_invoices


@frappe.whitelist()
def create_purchase_invoice_from_fta(docname: str):
    """
    Read the JSON file from UAE Incoming Invoices doc
    and create a Purchase Invoice from it as Draft
    """
    try:
        # 1. Get the UAE Incoming Invoices doc
        uae_doc = frappe.get_doc("UAE Incoming Invoices", docname)

        if not uae_doc.incoming_invoice_file:
            frappe.throw(_("No invoice file attached to this record"))

        # 2. Get file doc and read content
        try:
            file_doc = frappe.get_doc("File", {
                "file_url": uae_doc.incoming_invoice_file
            })
            file_content = file_doc.get_content()
        except Exception as e:
            frappe.throw(_(f"Could not read file: {str(e)}"))

        if isinstance(file_content, bytes):
            file_content = file_content.decode("utf-8")

        try:
            invoice_json = json.loads(file_content)
        except Exception as e:
            frappe.throw(_(f"Invalid JSON file: {str(e)}"))

        # 3. Let the provider's adapter read its own JSON format
        company = (
            frappe.defaults.get_user_default("Company")
            or frappe.db.get_single_value("Global Defaults", "default_company")
        )
        if not company:
            frappe.throw(_("Set a default Company for your user before importing incoming invoices."))
        parsed = _parse_with_adapter(company, invoice_json)

        supplier_name = parsed.get("supplier_name")
        vat_number = parsed.get("vat_number")

        # Try to find supplier by VAT or name
        supplier = None
        if vat_number:
            supplier = frappe.db.get_value("Supplier", {"tax_id": vat_number}, "name")
        if not supplier and supplier_name:
            supplier = frappe.db.get_value("Supplier", {"supplier_name": supplier_name}, "name")
        if not supplier:
            frappe.throw(_(f"Supplier not found: {supplier_name} (VAT: {vat_number}). Please create the supplier first."))

        # 4. Create Purchase Invoice
        pi = frappe.new_doc("Purchase Invoice")
        pi.company = company
        pi.supplier = supplier
        pi.posting_date = parsed.get("posting_date")
        pi.due_date = parsed.get("due_date")
        pi.currency = parsed.get("currency") or "AED"
        # update_stock removed — avoids stock account/warehouse mismatch error

        # Set document identifier if custom field exists
        if frappe.db.exists("Custom Field", {"dt": "Purchase Invoice", "fieldname": "custom_document_id"}):
            # Same Document ID as the UAE Incoming Invoices record, so
            # "Match & Approve" can find it again.
            pi.custom_document_id = uae_doc.document_id or parsed.get("document_id")

        # Exchange rate
        if parsed.get("conversion_rate"):
            pi.conversion_rate = parsed.get("conversion_rate")

        # 5. Account lookups for this company
        # Get default expense account (Cost of Goods Sold)
        expense_account = frappe.db.get_value(
            "Account",
            {
                "account_type": "Cost of Goods Sold",
                "company": company,
                "is_group": 0
            },
            "name"
        )

        # Fallback expense account if not found
        if not expense_account:
            expense_account = frappe.db.get_value(
                "Account",
                {
                    "account_name": "Cost of Goods Sold",
                    "company": company
                },
                "name"
            )

        # 6. Add invoice lines as items
        invoice_lines = parsed.get("lines") or []

        if not invoice_lines:
            frappe.throw(_("No invoice lines found in the JSON file"))

        for line in invoice_lines:
            item_name = line.get("name") or line.get("description")
            item_code = frappe.db.get_value("Item", {"item_name": item_name}, "name")

            if not item_code:
                item_code = frappe.db.get_value("Item", {"description": line.get("description")}, "name")

            if not item_code:
                frappe.throw(_(f"Item not found: {item_name}. Please create the item first."))

            pi.append("items", {
                "item_code": item_code,
                "item_name": line.get("name"),
                "description": line.get("description"),
                "qty": line.get("qty") or 1,
                "uom": line.get("uom") or "Nos",
                "rate": line.get("rate") or 0,
                "amount": line.get("amount") or 0,
                "expense_account": expense_account,
            })

        # 7. Add taxes
        vat_rate = invoice_lines[0].get("vat_rate")
        if vat_rate is None:
            vat_rate = 5

        tax_account = frappe.db.get_value(
            "Account",
            {"account_name": "VAT 5%", "company": company},
            "name"
        )

        if tax_account and vat_rate > 0:
            pi.append("taxes", {
                "charge_type": "On Net Total",
                "account_head": tax_account,
                "rate": vat_rate,
                "description": f"VAT {vat_rate}%"
            })

        # 8. Payment means - the JSON gives a bare code ("1"), the field
        # needs the full option ("1 - Instrument not defined")
        pm_option = _payment_means_option(parsed.get("payment_means_code"))
        if pm_option:
            pi.custom_payment_means_codes = pm_option

        # 9. Insert as Draft only — never 
        if uae_doc.submit_response:
            try:
                response_data = json.loads(uae_doc.submit_response)
            except Exception:
                response_data = {}
            if not isinstance(response_data, dict):
                response_data = {}
            data = response_data.get("data") if isinstance(response_data.get("data"), dict) else {}

            reporting_status = data.get("reporting_status") or response_data.get("reporting_status")
            invoice_status = response_data.get("status") or data.get("status")
            if not isinstance(reporting_status, str):
                reporting_status = None
            if not isinstance(invoice_status, str):
                invoice_status = None
            if reporting_status:
                pi.custom_reporting_status = reporting_status.title()

            if invoice_status:
                pi.custom_uae_einvoice_status = invoice_status.title()

    
        pi.flags.ignore_permissions = True
        pi.flags.ignore_mandatory = True
        pi.insert()

        # 10. Update UAE Incoming Invoice status
        frappe.db.set_value("UAE Incoming Invoices", docname, "status", "Submitted")
        frappe.db.commit()  # nosemgrep

        return {
            "purchase_invoice": pi.name,
            "message": f"Purchase Invoice {pi.name} created successfully as Draft"
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "create_purchase_invoice_from_fta")
        return {
            "error": True,
            "message": str(e)
        }