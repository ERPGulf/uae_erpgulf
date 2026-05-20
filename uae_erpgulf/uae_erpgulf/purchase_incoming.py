import frappe
import requests
import json
from frappe import _
from frappe.utils import now_datetime
from uae_erpgulf.uae_erpgulf.verify_token import get_valid_flick_token

@frappe.whitelist()
def simulate_incoming_document(doc):
    """
    Simulate an incoming invoice document in Flick UAE sandbox.
    """
    try:
        # Get Company document
        company_doc = frappe.get_doc("Company",  doc.company)

        # Required fields
        participant_id = company_doc.custom_participant_id
        auth_key = company_doc.custom_xflickauthkey
        base_url = company_doc.custom_base_url

        # Validations
        if not participant_id:
            frappe.throw(_("Participant ID is missing in Company"))

        if not base_url:
            frappe.throw(_("Base URL is missing in Company"))

        # Build URL
        url = f"{base_url}/v1/{participant_id}/simulate/incoming"

        # Get access token if needed
        access_token = get_valid_flick_token(company_doc.name)

        # Prepare headers
        if auth_key:
            headers = {
                "Content-Type": "application/json",
                "X-Flick-Auth-Key": auth_key
            }
        elif access_token:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            }
        else:
            frappe.throw(
                _("Both X-Flick Auth Key and Access Token are missing in Company")
            )

        # Request payload
        payload = {
            "type": "380",
            "issuing_party": {
                "legal_name": "Al Futtaim Trading LLC",
                "peppol_id": "0235:123456789012345",
                "vat_number": "300000000000001",
                "street_address": "",
                "city_address": "",
                "country_code": "AE"
            },
            "document": {}
        }

        # Send POST request
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=60
        )

        # Parse response
        try:
            response_json = response.json()
        except Exception:
            response_json = {
                "raw_response": response.text
            }

        # Save response in Company (optional custom field)
        if hasattr(company_doc, "custom_simulate_incoming_response"):
            company_doc.db_set(
                "custom_simulate_incoming_response",
                json.dumps(response_json, indent=2)
            )

        # Success response
        if response.status_code in [200, 201]:
            return {
                "status": "success",
                "message": _("Incoming document simulation completed successfully"),
                "http_status_code": response.status_code,
                "response": response_json
            }

        # Error response
        return {
            "status": "error",
            "message": _("Simulation failed"),
            "http_status_code": response.status_code,
            "response": response_json
        }

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Flick Incoming Document Simulation Error"
        )
        return {
            "status": "error",
            "message": str(e)
        }



@frappe.whitelist()
def get_incoming_documents(doc):
    """
    Fetch incoming documents from Flick API.
    """
    try:
        # Get Company document
        company_doc = frappe.get_doc("Company",  doc.company)

        # Required fields
        participant_id = company_doc.custom_participant_id
        auth_key = company_doc.custom_xflickauthkey
        base_url = company_doc.custom_base_url

        # Validations
        if not participant_id:
            frappe.throw(_("Participant ID is missing in Company"))

        if not base_url:
            frappe.throw(_("Base URL is missing in Company"))

        # Build URL
        url = f"{base_url}/v1/{participant_id}/documents"

        # Get access token if needed
        access_token = get_valid_flick_token(company_doc.name)

        # Prepare headers
        if auth_key:
            headers = {
                "X-Flick-Auth-Key": auth_key
            }
        elif access_token:
            headers = {
                "Authorization": f"Bearer {access_token}"
            }
        else:
            frappe.throw(
                _("Both X-Flick Auth Key and Access Token are missing in Company")
            )

        # Query parameters: only incoming documents
        params = {
            "direction": "incoming"
        }

        # Send GET request
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=60
        )

        # Parse response
        try:
            response_json = response.json()
        except Exception:
            response_json = {
                "raw_response": response.text
            }

        # Save response in Company (optional custom field)
        if hasattr(company_doc, "custom_incoming_documents_response"):
            company_doc.db_set(
                "custom_incoming_documents_response",
                json.dumps(response_json, indent=2)
            )

        # Success response
        if response.status_code == 200:
            return {
                "status": "success",
                "message": _("Incoming documents fetched successfully"),
                "http_status_code": response.status_code,
                "response": response_json
            }

        # Error response
        return {
            "status": "error",
            "message": _("Failed to fetch incoming documents"),
            "http_status_code": response.status_code,
            "response": response_json
        }

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Flick Get Incoming Documents Error"
        )
        return {
            "status": "error",
            "message": str(e)
        }








import frappe
import xml.etree.ElementTree as ET
from frappe import _
from decimal import Decimal, ROUND_HALF_UP


def r2(value):
    """Round to 2 decimals using ROUND_HALF_UP."""
    return float(
        Decimal(str(value)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
    )


@frappe.whitelist()
def create_purchase_invoice_from_xml(xml_content=None, file_url=None):
    """
    Create and submit Purchase Invoice from UAE PEPPOL/UBL XML.

    Parameters:
        xml_content (str): Raw XML content.
        file_url (str): Optional attached XML file URL.

    Returns:
        dict
    """

    # ---------------------------------------------------------
    # Load XML content
    # ---------------------------------------------------------
    if not xml_content and file_url:
        file_doc = frappe.get_doc("File", {"file_url": file_url})
        xml_content = file_doc.get_content()

    if not xml_content:
        frappe.throw(_("XML content is required"))

    # ---------------------------------------------------------
    # Parse XML
    # ---------------------------------------------------------
    ns = {
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
        "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    }

    root = ET.fromstring(xml_content)

    # ---------------------------------------------------------
    # Header Fields
    # ---------------------------------------------------------
    invoice_number = get_xml_text(root, ".//cbc:ID", ns)
    issue_date = get_xml_text(root, ".//cbc:IssueDate", ns)
    currency = get_xml_text(root, ".//cbc:DocumentCurrencyCode", ns) or "AED"
    supplier_name = get_xml_text(
        root,
        ".//cac:AccountingSupplierParty//cbc:RegistrationName",
        ns,
    )
    supplier_vat = get_xml_text(
        root,
        ".//cac:AccountingSupplierParty//cac:PartyTaxScheme/cbc:CompanyID",
        ns,
    )

    if not supplier_name:
        frappe.throw(_("Supplier name not found in XML"))

    # ---------------------------------------------------------
    # Amounts
    # ---------------------------------------------------------
    tax_amount = r2(
        get_xml_text(
            root,
            ".//cac:TaxTotal/cbc:TaxAmount",
            ns,
            0,
        )
    )

    net_total = r2(
        get_xml_text(
            root,
            ".//cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount",
            ns,
            0,
        )
    )

    grand_total = r2(
        get_xml_text(
            root,
            ".//cac:LegalMonetaryTotal/cbc:PayableAmount",
            ns,
            net_total + tax_amount,
        )
    )

    # ---------------------------------------------------------
    # Create or Get Supplier
    # ---------------------------------------------------------
    supplier = get_or_create_supplier(
        supplier_name=supplier_name,
        tax_id=supplier_vat
    )

    # ---------------------------------------------------------
    # Parse Invoice Lines
    # ---------------------------------------------------------
    lines = root.findall(".//cac:InvoiceLine", ns)
    items = []

    if lines:
        for line in lines:
            item_name = get_xml_text(
                line,
                ".//cac:Item/cbc:Name",
                ns,
            ) or "Imported Item"

            description = get_xml_text(
                line,
                ".//cac:Item/cbc:Description",
                ns,
            ) or item_name

            qty = float(
                get_xml_text(
                    line,
                    ".//cbc:InvoicedQuantity",
                    ns,
                    1,
                )
            )

            rate = float(
                get_xml_text(
                    line,
                    ".//cac:Price/cbc:PriceAmount",
                    ns,
                    0,
                )
            )

            if rate == 0:
                line_amount = float(
                    get_xml_text(
                        line,
                        ".//cbc:LineExtensionAmount",
                        ns,
                        0,
                    )
                )
                if qty:
                    rate = line_amount / qty

            item_code = get_or_create_item(
                item_name=item_name,
                description=description
            )

            items.append({
                "item_code": item_code,
                "item_name": item_name,
                "description": description,
                "qty": qty,
                "rate": r2(rate),
                "uom": "Nos",
            })
    else:
        # Fallback if XML has no InvoiceLine
        item_code = get_or_create_item(
            item_name="Imported Invoice Item",
            description="Imported from XML"
        )

        items.append({
            "item_code": item_code,
            "item_name": "Imported Invoice Item",
            "description": "Imported from XML",
            "qty": 1,
            "rate": net_total,
            "uom": "Nos",
        })

    # ---------------------------------------------------------
    # Duplicate Check
    # ---------------------------------------------------------
    existing = frappe.db.exists(
        "Purchase Invoice",
        {
            "supplier": supplier,
            "bill_no": invoice_number
        }
    )
    if existing:
        return {
            "message": "Purchase Invoice already exists",
            "purchase_invoice": existing
        }

    # ---------------------------------------------------------
    # Company
    # ---------------------------------------------------------
    company = frappe.defaults.get_global_default("company")
    if not company:
        frappe.throw(_("Default company is not set"))

    # ---------------------------------------------------------
    # Create Purchase Invoice
    # ---------------------------------------------------------
    pi = frappe.new_doc("Purchase Invoice")
    pi.company = company
    pi.supplier = supplier
    pi.bill_no = invoice_number
    pi.bill_date = issue_date
    pi.posting_date = issue_date
    pi.currency = currency
    pi.set_posting_time = 1
    pi.update_stock = 0
    pi.remarks = "Imported from UAE PEPPOL XML"

    # Append Items
    for row in items:
        pi.append("items", row)

    # ---------------------------------------------------------
    # Add Tax (if any)
    # ---------------------------------------------------------
    if tax_amount > 0 and net_total > 0:
        tax_rate = r2((tax_amount / net_total) * 100)

        pi.append("taxes", {
            "charge_type": "On Net Total",
            "account_head": get_default_tax_account(company),
            "rate": tax_rate,
            "description": f"VAT {tax_rate}%"
        })

    # ---------------------------------------------------------
    # Save and Submit
    # ---------------------------------------------------------
    pi.insert(ignore_permissions=True)
    pi.submit()
    frappe.db.commit()

    return {
        "message": "Purchase Invoice created successfully",
        "purchase_invoice": pi.name,
        "supplier": supplier,
        "bill_no": invoice_number,
        "net_total": net_total,
        "tax_amount": tax_amount,
        "grand_total": grand_total
    }


# =========================================================
# Helper Functions
# =========================================================

def get_xml_text(node, xpath, ns, default=None):
    """Safely get text from XML."""
    element = node.find(xpath, ns)
    if element is not None and element.text:
        return element.text.strip()
    return default


def get_or_create_supplier(supplier_name, tax_id=None):
    """Create Supplier if not exists."""
    existing = frappe.db.exists(
        "Supplier",
        {"supplier_name": supplier_name}
    )
    if existing:
        return existing

    supplier = frappe.new_doc("Supplier")
    supplier.supplier_name = supplier_name
    supplier.supplier_group = get_default_supplier_group()
    if tax_id:
        supplier.tax_id = tax_id
    supplier.insert(ignore_permissions=True)

    return supplier.name


def get_or_create_item(item_name, description=None):
    """Create Item if not exists."""
    existing = frappe.db.exists(
        "Item",
        {"item_name": item_name}
    )
    if existing:
        return existing

    item = frappe.new_doc("Item")
    item.item_code = frappe.scrub(item_name).upper()[:50]
    item.item_name = item_name
    item.description = description or item_name
    item.item_group = get_default_item_group()
    item.stock_uom = "Nos"
    item.is_stock_item = 0
    item.insert(ignore_permissions=True)

    return item.name


def get_default_supplier_group():
    """Return a non-group Supplier Group."""
    group = frappe.db.get_value(
        "Supplier Group",
        {"is_group": 0},
        "name"
    )
    if not group:
        frappe.throw(_("No non-group Supplier Group found"))
    return group


def get_default_item_group():
    """Return a non-group Item Group."""
    group = frappe.db.get_value(
        "Item Group",
        {"is_group": 0},
        "name"
    )
    if not group:
        frappe.throw(_("No non-group Item Group found"))
    return group


def get_default_tax_account(company):
    """Return first tax account for the company."""
    account = frappe.db.get_value(
        "Account",
        {
            "company": company,
            "account_type": "Tax",
            "is_group": 0
        },
        "name"
    )

    if not account:
        account = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "is_group": 0
            },
            "name"
        )

    if not account:
        frappe.throw(_("No suitable tax account found"))

    return account