"""get purchase invoice"""
import frappe
import json
from frappe import _


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

        # 3. Parse supplier from receiving_party
        receiving_party = invoice_json.get("receiving_party", {})
        supplier_name = receiving_party.get("trade_name") or receiving_party.get("legal_name")
        vat_number = receiving_party.get("vat_number")

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
        pi.supplier = supplier
        pi.posting_date = invoice_json.get("issue_date")
        pi.due_date = invoice_json.get("due_date")
        pi.currency = invoice_json.get("document_currency", "AED")
        # update_stock removed — avoids stock account/warehouse mismatch error

        # Set document identifier if custom field exists
        if frappe.db.exists("Custom Field", {"dt": "Purchase Invoice", "fieldname": "custom_document_id"}):
            pi.custom_document_id = invoice_json.get("document_identifier")

        # Exchange rate
        if invoice_json.get("currency_exchange_rate"):
            pi.conversion_rate = invoice_json.get("currency_exchange_rate")

        # 5. Get company for account lookups
        company = frappe.defaults.get_user_default("Company")

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
        invoice_lines = invoice_json.get("invoice_lines", [])

        if not invoice_lines:
            frappe.throw(_("No invoice lines found in the JSON file"))

        for line in invoice_lines:
            item_name = line.get("name") or line.get("description")
            item_code = frappe.db.get_value("Item", {"item_name": item_name}, "name")

            if not item_code:
                item_code = frappe.db.get_value("Item", {"description": line.get("description")}, "name")

            if not item_code:
                frappe.throw(_(f"Item not found: {item_name}. Please create the item first."))

            item_row = {
                "item_code": item_code,
                "item_name": line.get("name"),
                "description": line.get("description"),
                "qty": float(line.get("invoiced_quantity", 1)),
                "uom": line.get("uom", "Nos"),
                "rate": float(line.get("unit_price", 0)),
                "amount": float(line.get("line_extension_amount", 0)),
                "expense_account": expense_account,
            }

            pi.append("items", item_row)

        # 7. Add taxes
        vat_rate = 5  # default
        if invoice_lines:
            first_line = invoice_lines[0]
            vat_rate = float(first_line.get("vat_percentage", 5))

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

        # 8. Payment means
        payment_means = invoice_json.get("payment_means", [])
        if payment_means:
            pm = payment_means[0] if isinstance(payment_means[0], dict) else {}
            pm_code = pm.get("payment_means_code") or pm.get("payment_means", {}).get("payment_means_code")
            if pm_code and frappe.db.exists("Custom Field", {"dt": "Purchase Invoice", "fieldname": "custom_payment_means_codes"}):
                pi.custom_payment_means_codes = pm_code

        # 9. Insert as Draft only — never 
        if uae_doc.submit_response:
            response_data = json.loads(uae_doc.submit_response)

            reporting_status = response_data.get("data", {}).get("reporting_status")
            invoice_status = (
                response_data.get("status")
                or response_data.get("data", {}).get("status")
            )
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