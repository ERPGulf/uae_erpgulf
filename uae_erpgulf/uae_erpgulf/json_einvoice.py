import frappe
import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from frappe import _
from uae_erpgulf.uae_erpgulf.country_code import country_code_mapping
import json
def r2(val):
    return str(Decimal(val).quantize(Decimal("0.01"), ROUND_HALF_UP))


def get_icv_code(invoice_number):
    """
    Extracts the numeric part from the invoice number to generate the ICV code.
    """
    try:
        return re.sub(r"\D", "", invoice_number)
    except TypeError as e:
        frappe.throw(_("Type error in getting ICV number: " + str(e)))
    except re.error as e:
        frappe.throw(_("Regex error in getting ICV number: " + str(e)))

def get_address(sales_invoice_doc):
    """
    Returns the Company address linked to the Sales Invoice's Company.
    Uses only addresses marked as 'Your Company Address'.
    """

    address_list = frappe.get_all(
        "Address",
        fields=[
            "name",
            "address_line1",
            "address_line2",
            # "custom_building_number",
            "city",
            "pincode",
            "state",
            "phone",
            "country",
        ],
        filters={
            "is_your_company_address": 1,
            "link_doctype": "Company",
            "link_name": sales_invoice_doc.company,
        },
        order_by="creation asc",
        limit=1,
    )

    if not address_list:
        frappe.throw(
            _(
                f"No company address found for Company '{sales_invoice_doc.company}'. "
                f"Please add and mark an address as 'Your Company Address'."
            )
        )

    return address_list[0]
def get_line_extension_amount(sales_invoice_doc):
    if not sales_invoice_doc.taxes or sales_invoice_doc.taxes[0].included_in_print_rate == 0:
        line_extension_amount = str(round(abs(sales_invoice_doc.total), 2))
    else:
        if sales_invoice_doc.discount_amount:
            line_extension_amount = str(
                round(
                    abs(
                        sales_invoice_doc.base_net_total
                        + sales_invoice_doc.get("discount_amount", 0.0)
                    ),
                    2,
                )
            )
        else:
            line_extension_amount = str(
                round(abs(sales_invoice_doc.base_net_total), 2)
            )
    return line_extension_amount


def get_tax_exc(sales_invoice_doc):
    
    if sales_invoice_doc.taxes[0].included_in_print_rate == 0:
            tax_exclusive_amount = str(
                round(
                    abs(
                        sales_invoice_doc.total
                        - sales_invoice_doc.get("discount_amount", 0.0)
                    ),
                    2,
                )
            )
    else:
        if sales_invoice_doc.discount_amount ==0:
            tax_exclusive_amount = str(
                round(
                    abs(
                        sales_invoice_doc.base_net_total
                        - sales_invoice_doc.get("discount_amount", 0.0)
                    ),
                    2,
                )
            )
        else:
            tax_exclusive_amount = str(
                round(
                    abs(
                        sales_invoice_doc.base_net_total
                    ),
                    2,
                )
            )
    return tax_exclusive_amount

def get_tax_inclusive(sales_invoice_doc):
    if sales_invoice_doc.taxes[0].included_in_print_rate == 0:
            taxable_amount_1 = sales_invoice_doc.total - sales_invoice_doc.get(
                "discount_amount", 0.0
            )
    else:
        taxable_amount_1 = (
            sales_invoice_doc.base_net_total
            - sales_invoice_doc.get("discount_amount", 0.0)
        )
    tax_amount_without_retention = (
        taxable_amount_1 * float(sales_invoice_doc.taxes[0].rate) / 100
    )
    if sales_invoice_doc.taxes[0].included_in_print_rate == 0:
        tax_inclusive_amount = str(
            round(
                abs(
                    sales_invoice_doc.total
                    - sales_invoice_doc.get("discount_amount", 0.0)
                )
                + abs(tax_amount_without_retention),
                2,
            )
        )
    else:
        if sales_invoice_doc.discount_amount ==0:

            tax_inclusive_amount = str(
                round(
                    abs(
                        sales_invoice_doc.base_net_total
                        - sales_invoice_doc.get("discount_amount", 0.0)
                    )
                    + abs(tax_amount_without_retention),
                    2,
                )
            )
        else:
            tax_inclusive_amount = str(
                round(
                    abs(
                        sales_invoice_doc.base_net_total
                    )
                    + abs(tax_amount_without_retention),
                    2,
                )
            )
    return tax_inclusive_amount


def get_payable_amount(sales_invoice_doc):
    if sales_invoice_doc.taxes[0].included_in_print_rate == 0:
            taxable_amount_1 = sales_invoice_doc.total - sales_invoice_doc.get(
                "discount_amount", 0.0
            )
    else:
        taxable_amount_1 = (
            sales_invoice_doc.base_net_total
            - sales_invoice_doc.get("discount_amount", 0.0)
        )
    tax_amount_without_retention = (
        taxable_amount_1 * float(sales_invoice_doc.taxes[0].rate) / 100
    )
    if sales_invoice_doc.taxes[0].included_in_print_rate == 0:
        total_amount = round(
            abs(
                sales_invoice_doc.total
                - sales_invoice_doc.get("discount_amount", 0.0)
            )
            + abs(tax_amount_without_retention),
            2,
        )
    else:
        if sales_invoice_doc.discount_amount ==0:
            total_amount = round(
                abs(
                    sales_invoice_doc.base_net_total
                    - sales_invoice_doc.get("discount_amount", 0.0)
                )
                + abs(tax_amount_without_retention),
                2,
            )
        else:
            total_amount=round(
                abs(
                    sales_invoice_doc.base_net_total
                )
                + abs(tax_amount_without_retention),
                2,
            )
    return total_amount

def build_uae_invoice_json(invoice_number):
    sales_invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
    company_doc = frappe.get_doc("Company", sales_invoice_doc.company)
    customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)
    address = get_address(sales_invoice_doc)
    address_data = None

    if sales_invoice_doc.customer_address:
        address_data = frappe.get_doc("Address", sales_invoice_doc.customer_address)
    elif customer_doc.customer_primary_address:
        address_data = frappe.get_doc("Address", customer_doc.customer_primary_address)

    if not address_data:
        frappe.throw(_("Customer address not found"))

    # ---------------- COUNTRY CODE ----------------
    country_dict = country_code_mapping()

    if address_data.country and address_data.country.lower() in country_dict:
        country_code1 = country_dict[address_data.country.lower()]
    else:
        country_code1 = "AE" 
    line_extension_amount = get_line_extension_amount(sales_invoice_doc)  
    tax_exclusive_amount = get_tax_exc(sales_invoice_doc)
    tax_inclusive_amount = get_tax_inclusive(sales_invoice_doc)
    payable_amount = get_payable_amount(sales_invoice_doc)
 

    # Assuming payable_amount and tax_inclusive_amount are strings
    payable_amount_float = float(payable_amount)
    tax_inclusive_amount_float = float(tax_inclusive_amount)

    payable_rounding_amount = (payable_amount_float - tax_inclusive_amount_float)

    invoice = {
        "invoice_id": sales_invoice_doc.name,
        "issue_date": str(sales_invoice_doc.posting_date),
        "issue_time": str(sales_invoice_doc.posting_time),
        "due_date": str(sales_invoice_doc.due_date) if sales_invoice_doc.due_date else None,
        "invoice_type_code": "381" if sales_invoice_doc.is_return else "380",
        "document_currency_code": sales_invoice_doc.currency,
        "note": "Tax Invoice",
        "tax_point_date": str(sales_invoice_doc.due_date) if sales_invoice_doc.due_date else None,
        "accounting_cost": "4025:123:4343", #sales_invoice_doc.cost_centre
        "buyer_reference": get_icv_code(invoice_number),

        "invoice_period": {
            "start_date": sales_invoice_doc.posting_date.isoformat(),
            "end_date": sales_invoice_doc.due_date.isoformat() if sales_invoice_doc.due_date else None,
            "description_code": "OTH"
        },

        "order_reference": {
            "id": "PO-001/23",
            "sales_order_id": "SO-001/23"
        },


        "billing_reference": {
            
            "invoice_document_reference": {
                "id": str(invoice_number),
                "issue_date": str(sales_invoice_doc.posting_date)
            }
        },

        "accounting_supplier_party": {
            "party": {
                "endpoint_id": {
                    "value": company_doc.tax_id,
                    "scheme_id": "0235"
                },
                "party_name": sales_invoice_doc.company,
                "postal_address": {
                    "street_name": address.get("address_line1"),
                    "additional_street_name": address.get("address_line2"),
                    "city_name": address.get("city"),
                    "postal_zone": address.get("pincode"),
                    "country_subentity":  address.get("state"),
                    "address_line": address.get("address_line2"),
                    "country": {"identification_code": country_code1}
                },
                "party_tax_scheme": {
                    "company_id": company_doc.tax_id,
                    "tax_scheme": {"id": "VAT"}
                },
                "party_legal_entity": {
                    "registration_name": sales_invoice_doc.company,
                    "company_id": {
                        "value": company_doc.tax_id,
                        "scheme_agency_id": "TL",
                        "scheme_agency_name": "Trade License issuing Authority"
                    },
                    "company_legal_form": "Merchant"
                },
                "contact": {"name": sales_invoice_doc.company,
                "phone":address.get("phone"),

                }
            }
        },

        "accounting_customer_party": {
            "party": {
                "endpoint_id": {
                    "value": customer_doc.tax_id ,
                    "scheme_id": "0235"
                },
                "party_name": customer_doc.customer_name,
                "postal_address": {
                    "street_name": address_data.address_line1,
                    "additional_street_name": address_data.address_line2,
                    "city_name": address_data.city,
                    "postal_zone": address_data.pincode,
                    "country_subentity": address_data.state,
                    "address_line": address_data.address_line2,
                    "country": {"identification_code": country_code1}
                },
                "party_tax_scheme": {
                    "company_id": customer_doc.tax_id ,
                    "tax_scheme": {"id": "VAT"}
                },
                "party_legal_entity": {
                    "registration_name": customer_doc.customer_name,
                    "company_id": {
                        "value":customer_doc.tax_id ,
                        "scheme_agency_id": "TL",
                        "scheme_agency_name": "Trade License issuing Authority"
                    }
                },
                "contact": {"name": customer_doc.customer_name,
                "phone": address_data.phone}
            }
        },
        "legal_monetary_total": {
                "line_extension_amount": line_extension_amount,
                "tax_exclusive_amount": tax_exclusive_amount,
                "tax_inclusive_amount": tax_inclusive_amount,
                "allowance_total_amount":  str(abs(sales_invoice_doc.get("discount_amount", 0.0))),
                "charge_total_amount": str(abs(sales_invoice_doc.get("base_change_amount", 0.0))),
                "prepaid_amount": 0,
                "payable_rounding_amount": payable_rounding_amount,
                "payable_amount": payable_amount,
                "currency_id": sales_invoice_doc.currency
            },
            

        "invoice_line": [],
        "invoice_totals": {}
    }

    total_net = Decimal("0")
    total_tax = Decimal("0")

    vat_rate = Decimal(sales_invoice_doc.taxes[0].rate if sales_invoice_doc.taxes else 0)

    for idx, item in enumerate(sales_invoice_doc.items, 1):
        net = Decimal(item.amount)
        tax = net * vat_rate / 100

        total_net += net
        total_tax += tax
        tax_dict = json.loads(item.item_tax_rate)

        # Get the first value
        tax_rate = list(tax_dict.values())[0]
        invoice["invoice_line"].append({
            "id": str(idx),
            "note": "Please check the invoice",
            "invoiced_quantity": str(item.qty),
            "invoiced_quantity_unit_code": item.uom,
            "currency_id": sales_invoice_doc.price_list_currency,
            "accounting_cost": item.cost_center,
            "line_extension_amount": r2(net),
            "item": {
                "name": item.item_name,
                "description": item.description,
                "commodity_code": item.item_code,
                "classification": [{
                    "code": item.item_code,
                    "scheme": "HS"
                }] ,
                # if item.custom_hs_code else [],
                "vat_category_code": "Standard",
                # "vat_category_code": item.custom_vat_category,
                "vat_percent": r2(vat_rate)
            },
            "price": {
                "price_amount": r2(item.rate),
                "currency_id":sales_invoice_doc.currency,
                "base_quantity": "1",
                "base_quantity_unit_code": item.uom
            }
        })

    invoice["invoice_totals"] = {
        "line_extension_amount": r2(total_net),
        "tax_exclusive_amount": r2(total_net - Decimal(sales_invoice_doc.discount_amount or 0)),
        "tax_inclusive_amount": r2(total_net + total_tax),
        "allowance_total_amount": r2(abs(Decimal(sales_invoice_doc.discount_amount or 0))),
        "payable_amount": r2(total_net + total_tax)
    }

    return invoice
def save_and_attach_invoice_json(invoice_number):
    """
    Builds UAE invoice JSON, saves it as a file, and attaches it to the Sales Invoice.
    If the file already exists, it will be overwritten.
    """

    invoice_json = build_uae_invoice_json(invoice_number)
    json_content = json.dumps(invoice_json, indent=4, ensure_ascii=False)

    file_name = f"{invoice_number}_uae_invoice.json"

    # 🔎 Check if file already exists
    existing_file = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Sales Invoice",
            "attached_to_name": invoice_number,
            "file_name": file_name,
        },
        limit=1,
    )

    if existing_file:
        # 🔁 Overwrite existing file
        file_doc = frappe.get_doc("File", existing_file[0].name)
        file_doc.content = json_content
        file_doc.save(ignore_permissions=True)

    else:
        # ➕ Create new file
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": file_name,
            "is_private": 1,
            "content": json_content,
            "attached_to_doctype": "Sales Invoice",
            "attached_to_name": invoice_number,
        })
        file_doc.insert(ignore_permissions=True)

    frappe.db.commit()

    return {
        "file_name": file_doc.file_name,
        "file_url": file_doc.file_url,
    }

@frappe.whitelist()
def send_invoice_json(invoice_number):
    if not invoice_number:
        frappe.throw(_("Sales Invoice not provided"))

    result = save_and_attach_invoice_json(invoice_number)

    return {
        "message": _("Invoice JSON generated and attached successfully"),
        "file_url": result["file_url"]
    }
