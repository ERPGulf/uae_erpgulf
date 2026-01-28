import frappe
import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from frappe import _
from uae_erpgulf.uae_erpgulf.country_code import country_code_mapping
import json
from datetime import timedelta

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



def get_invoice_type_code(sales_invoice_doc):
    """
    Returns invoice_type_code based on Sales Invoice flags:
    """
    if sales_invoice_doc.is_return == 1:
        return "381"
    if sales_invoice_doc.custom_credit_note_related_to_goods_or_services_out_of_scope == 1:
        return "81"
    if sales_invoice_doc.custom_invoice_out_of_scope_of_tax == 1:
        return "480"
    return "380"

def get_due_date(sales_invoice_doc, issue_date):
    """
    IBT-009 / ibr-127-ae compliant due date resolver
    """
    if sales_invoice_doc.is_return == 1:
        return None
    if sales_invoice_doc.custom_credit_note_related_to_goods_or_services_out_of_scope == 1:
        return None
    if getattr(sales_invoice_doc, "custom_invoice_transaction_type_code", None) == "X1XXXXX : Deemed supply transaction":
        return None
    if sales_invoice_doc.outstanding_amount > 0:
        if not sales_invoice_doc.due_date:
            frappe.throw(
                "Payment Due Date (IBT-009) is mandatory when Outstanding Amount > 0"
            )
        if sales_invoice_doc.due_date < issue_date:
            frappe.throw(
                "Payment Due Date must be equal to or after the Issue Date"
            )
        return sales_invoice_doc.due_date.strftime("%Y-%m-%d")
    return None

def get_invoice_period(sales_invoice_doc):
    """
    IBG-14 / UAE compliant InvoicePeriod resolver
    """
    ALLOWED_DESCRIPTION_CODES = {
        "DLY", "WKY", "Q15", "MTH", "Q45",
        "Q60", "QTR", "YRL", "HYR", "OTH"
    }
    start_date = sales_invoice_doc.posting_date
    end_date = sales_invoice_doc.due_date
    description_code = sales_invoice_doc.custom_frequency_billing_code_list
    if start_date and end_date and not description_code:
        frappe.throw(
            "Please select a Frequency of Billing (Invoice Period Description Code)"
        )
    if description_code and description_code not in ALLOWED_DESCRIPTION_CODES:
        frappe.throw(
            f"Invalid Invoice Period Description Code: {description_code}"
        )
    if end_date and not start_date:
        frappe.throw(
            "Invoice Period Start Date is mandatory when End Date is provided"
        )

    if getattr(sales_invoice_doc, "custom_invoice_transaction_type_code", None) == "X1XXXXX : Deemed supply transaction":
        if not start_date or not end_date or not description_code:
            frappe.throw(
                "Invoice Period (Start Date, End Date and Frequency) "
                "is mandatory for Summary Invoices"
            )
    if not start_date and not end_date:
        return None

    return {
        "start_date": start_date.strftime("%Y-%m-%d") if start_date else None,
        "end_date": end_date.strftime("%Y-%m-%d") if end_date else None,
        "description_code": description_code
    }

def get_invoice_notes(sales_invoice_doc):
    """
    IBT-022 / ibr-160-ae compliant Invoice Note resolver
    """
    frequency_code = sales_invoice_doc.custom_frequency_billing_code_list
    invoice_note = getattr(sales_invoice_doc, "custom_invoice_note", None)
    if frequency_code == "OTH" and not invoice_note:
        frappe.throw(
            "Invoice Note (IBT-022) is mandatory when Frequency of Billing is 'OTH'"
        )
    return invoice_note

def get_issue_time(sales_invoice_doc):
    issue_time = sales_invoice_doc.posting_time
    if not issue_time:
        return None
    if isinstance(issue_time, timedelta):
        total_seconds = int(issue_time.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return issue_time.strftime("%H:%M:%S")


def get_tax_point_date(sales_invoice_doc):
    """
    Returns tax_point_date as due_date (if available),
    but NOT for credit notes and must be before issue date.
    """
    if sales_invoice_doc.is_return == 1:
        return None
    if sales_invoice_doc.custom_credit_note_related_to_goods_or_services_out_of_scope == 1:
        return None
    if not sales_invoice_doc.due_date:
        return None
    issue_date = sales_invoice_doc.posting_date
    tax_point_date =  issue_date - timedelta(days=1)
    if tax_point_date >= issue_date:
        frappe.throw("Tax Point Date must be before Invoice Issue Date")

    return tax_point_date.strftime("%Y-%m-%d")


from decimal import Decimal, ROUND_HALF_UP

def get_currency_exchange_rate(sales_invoice_doc):
    """
    Returns currency exchange rate (cbc:ExchangeRate) for AED conversion
    """
    invoice_currency = sales_invoice_doc.currency
    if invoice_currency == "AED":
        return None
    exchange_rate = sales_invoice_doc.conversion_rate
    if not exchange_rate:
        frappe.throw("Currency exchange rate is mandatory when invoice currency is not AED")
    exchange_rate = Decimal(exchange_rate).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return float(exchange_rate)



def get_document_currency(sales_invoice_doc):
    """
    Returns document currency code (cbc:DocumentCurrencyCode)
    """
    currency = sales_invoice_doc.currency
    if not currency:
        frappe.throw("Invoice currency code (IBT-005) is mandatory")
    if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
        frappe.throw(
            "Invoice currency code must be a valid ISO 4217 alpha-3 code"
        )
    return currency.upper()

def get_transaction_type_code(sales_invoice_doc):
    """
    Extracts the 7-char transaction type pattern
    """
    raw = getattr(
        sales_invoice_doc,
        "custom_invoice_transaction_type_code",
        None
    )
    if not raw:
        return None
    return raw.split(":")[0].strip()




def validate_receiving_party_fields(
    sales_invoice_doc,
    customer_doc,
    address_data,
    transaction_type_code,
    # items
):
    errors = []

    is_credit_note = sales_invoice_doc.is_return == 1
    is_out_of_scope = sales_invoice_doc.custom_invoice_out_of_scope_of_tax == 1


    if not customer_doc.customer_name:
        errors.append("IBR-007: Legal name (IBT-044) MUST be provided")
    if not address_data.address_line1:
        errors.append("IBR-144-ae: Address line 1 (IBT-050) MUST be provided")
    if not address_data.city:
        errors.append("IBR-144-ae: City (IBT-052) MUST be provided")
    if not address_data.emirate:
        errors.append("IBR-144-ae: Country subdivision / Emirate (IBT-054) MUST be provided")
    if not address_data.pincode:
        errors.append("postal zone MUST be provided")
    if not address_data.country:
        errors.append("IBR-008: Country code (IBT-055) MUST be provided")
    if not address_data.email_id:
        errors.append("IBR-011: Electronic email id (IBT-049) MUST be provided")
    if is_credit_note or is_out_of_scope:
        if not customer_doc.custom_trade_license_number:
            errors.append(
                "IBR-136-ae: Legal registration identifier (IBT-047) "
                "MUST be present for Credit Note or Out of Scope invoice"
            )
    if transaction_type_code != "XXXXXXX1":  # Not export
        if not customer_doc.tax_id and not customer_doc.custom_trade_license_number:
            errors.append(
                "IBR-135-ae: Either VAT identifier (IBT-048) "
                "or legal identifier (IBT-046) MUST be present"
            )

    # for item in items:
    #     if item.get("vat_category") == "Reverse Charge":
    #         if not customer_doc.tax_id:
    #             errors.append(
    #                 "IBR-103-ae: VAT identifier (IBT-048) MUST be provided "
    #                 "for Reverse Charge items"
    #             )
    #         break
    if transaction_type_code and transaction_type_code.startswith("1"):
        if not customer_doc.custom_fz_beneficiary_id:
            errors.append(
                "IBR-007-ae: FZ Beneficiary ID (BTAE-01) MUST be provided "
                "for Free Trade Zone transaction"
            )
    if errors:
        frappe.throw("<br>".join(errors))


def get_item_data(sales_invoice_doc, vat_rate):
    total_net = Decimal(0)
    total_tax = Decimal(0)
    invoice = {"invoice_line": []}

    def r2(val):
        return float(Decimal(val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    # First, check if any item has an Item Tax Template
    any_item_tax_template = any(item.item_tax_template for item in sales_invoice_doc.items)

    for idx, item in enumerate(sales_invoice_doc.items, 1):
        # Validation
        if item.qty <= 0:
            frappe.throw(f"Invoiced quantity must be greater than zero for item {item.item_name}")

        if not item.custom_item_type_codes:
            frappe.throw(f"Item type (Goods / Services / Both) missing for item {item.item_name}")
        if item.custom_item_type_codes == "G - Goods" and not item.custom_hs_code_:
            frappe.throw(f"HS code missing for item {item.item_name}")

        if item.custom_item_type_codes == "S - Services" and not item.custom_sac_code:
            frappe.throw(f"SAC code missing for item {item.item_name}")

        if item.custom_item_type_codes == "B - Both" and (not item.custom_hs_code_ or not item.custom_sac_code):
            frappe.throw(f"HS/SAC code missing for item {item.item_name}")

        # If any item has an item tax template, enforce it for all
        if any_item_tax_template and not item.item_tax_template:
            frappe.throw(f"Item {item.item_name} must have an Item Tax Template because other items have one.")

        # Classification & commodity
        if item.custom_item_type_codes == "G - Goods":
            classification_code = item.custom_hs_code_
            hs_code = item.custom_hs_code_
            sac_code = None
            commodity_code = "G"
        elif item.custom_item_type_codes == "S - Services":
            classification_code = item.custom_sac_code
            hs_code = None
            sac_code = item.custom_sac_code
            commodity_code = "S"
        elif item.custom_item_type_codes == "B - Both":
            classification_code = item.custom_hs_code_  # HS primary
            hs_code = item.custom_hs_code_
            sac_code = item.custom_sac_code
            commodity_code = "B"

        # Amounts
        net = Decimal(item.amount)
        total_net += net

        # Determine VAT category and percentage
        if item.item_tax_template:
            item_tax_template = frappe.get_doc("Item Tax Template", item.item_tax_template)
            vat_category = item_tax_template.custom_vat_category or sales_invoice_doc.custom_vat_category
            if item_tax_template.taxes:
                tax_rate = item_tax_template.taxes[0].tax_rate
            else:
                tax_rate = vat_rate
        else:
            vat_category = sales_invoice_doc.custom_vat_category
            tax_rate = vat_rate

        tax = net * Decimal(tax_rate) / Decimal(100)
        total_tax += tax

        # Invoice line
        invoice_line = {
            "id": str(idx),
            "note": "Please check the invoice",
            "invoiced_quantity": str(item.qty),
            "uom": item.uom,
            "accounting_cost": item.cost_center,
            "name": item.item_name,
            "description": item.description,
            "commodity_code": commodity_code,
            "hs_code": hs_code,
            "sac_code": sac_code,
            "vat_category": vat_category,
            "vat_percentage": r2(tax_rate),
            "unit_price": r2(item.rate),
            "base_quantity": "1"
        }

        invoice["invoice_line"].append(invoice_line)

    return invoice, total_net, total_tax
        
def get_payment_means(sales_invoice_doc):
    """
    UAE / PEPPOL compliant PaymentMeans builder
    """
    if sales_invoice_doc.is_return == 1:
        return None
    if getattr(
        sales_invoice_doc,
        "custom_invoice_transaction_type_code",
        None
    ) == "X1XXXXX : Deemed supply transaction":
        return None

    payment_option = sales_invoice_doc.custom_payment_means_codes

    if not payment_option:
        frappe.throw("Payment means type code (IBT-081) is mandatory")
    payment_code, payment_name = payment_option.split(" - ", 1)

    APPROVED_PAYMENT_MEANS = {
        "1": "Instrument not defined",
        "10": "Cash",
        "20": "Cheque",
        "30": "Credit transfer",
        "31": "Debit transfer",
        "42": "Payment to bank account",
        "48": "Bank card",
        "49": "Direct debit",
        "55": "Debit card",
        "58": "SEPA credit transfer",
    }
    if payment_code not in APPROVED_PAYMENT_MEANS:
        frappe.throw(
            f"Invalid payment means code {payment_code}. "
            f"Must be from UN/ECE 4461 approved subset."
        )

    payment_means = {
        "payment_means_code": payment_code,
        "payment_means_code_name": payment_name,
    }
    if payment_code in ("30", "58"):
        if not sales_invoice_doc.company_bank_account:
            frappe.throw(
                "Payment account bank (IBT-084) is mandatory for Credit Transfer"
            )

        bank = frappe.get_doc(
            "Bank Account",
            sales_invoice_doc.company_bank_account
        )

        payment_means["payee_financial_account"] = {
            "id": bank.bank_account_no,
            "id_scheme_id": "IBAN",
            "name": bank.account_name,
            "financial_institution_branch": {
                "id": bank.branch_code or ""
            }
        }

    # Card payments
    if payment_code in ("48", "55"):
        payment_means["card_account"] = {
            "primary_account_number_id": "XXXXXXXXXXXX" + (
                sales_invoice_doc.card_last_4_digits or "0000"
            ),
            "network_id": sales_invoice_doc.card_network or "UNKNOWN",
            "holder_name": (
                sales_invoice_doc.card_holder_name
                or sales_invoice_doc.customer_name
            )
        }

    return {
        "payment_means": [payment_means]
    }


def build_uae_invoice_json(invoice_number):
    sales_invoice_doc = frappe.get_doc("Sales Invoice", invoice_number)
    company_doc = frappe.get_doc("Company", sales_invoice_doc.company)
    if company_doc.custom_uae_einvoice_enabled !=1 :
        frappe.msgprint("UAE E-invoicing not Enabled....pls enable to submit PEPPOL")
    customer_doc = frappe.get_doc("Customer", sales_invoice_doc.customer)
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
 
    payable_amount_float = float(payable_amount)
    tax_inclusive_amount_float = float(tax_inclusive_amount)

    payable_rounding_amount = (payable_amount_float - tax_inclusive_amount_float)

    transaction_code = get_transaction_type_code(sales_invoice_doc)
    is_ftz = transaction_code and transaction_code.startswith("1")
    validate_receiving_party_fields(sales_invoice_doc,customer_doc,address_data,transaction_code)
    receiving_party = {
                "trade_name":  customer_doc.customer_name,
                "peppol_id":  customer_doc.tax_id,
                "street_address": address_data.address_line1,
                "city_address": address_data.city,
                "additional_street_address": address_data.address_line2,
                "postal_zone": address_data.pincode,
                "emirates_code": address_data.emirate,
                "additional_address_lines":  address_data.address_line2,
                "country_code": country_code1 ,
                "vat_number": customer_doc.tax_id ,
                "legal_name":  customer_doc.customer_name,
                # "identifiers":  [
                #         {
                #             "type": "TL",
                #             "value": "112345679000001"
                #         }
                #         ],
                "contact_name" :  customer_doc.customer_name,
                "contact_telephone": address_data.phone ,
                "contact_email": address_data.email_id,
    }
    if customer_doc.get("custom_legal_registration_identifier_type") == "Commercial/Trade license":
        if not customer_doc.custom_trade_license_number:
            frappe.throw(
                "custom_trade_license_number is mandatory when legal registartion is  "
                "Commercial/Trade license"
                
            )    
        receiving_party["identifiers"] = [{
            "type": "TL",
            "value": customer_doc.custom_trade_license_number,
        }]
    if is_ftz:
        if not customer_doc.custom_fz_beneficiary_id:
            frappe.throw(
                "FZ Beneficiary ID (BTAE-01) is mandatory for "
                "Free Trade Zone transactions (1XXXXXX)"
            )

        receiving_party["fz_beneficiary_id"] = (
            customer_doc.custom_fz_beneficiary_id
        )

    
    issue_date = sales_invoice_doc.posting_date

    invoice = {
        "document_identifier": sales_invoice_doc.name,
        "issue_date": str(sales_invoice_doc.posting_date),
        "issue_time":get_issue_time(sales_invoice_doc),
        "due_date": get_due_date(sales_invoice_doc, issue_date),
        "document_type": get_invoice_type_code(sales_invoice_doc),
        "note":get_invoice_notes(sales_invoice_doc),

        "tax_point_date":get_tax_point_date(sales_invoice_doc), #this feild is optional and having confus
        
        "document_currency":get_document_currency(sales_invoice_doc),
        # "currency_exchange_rate" :get_currency_exchange_rate(sales_invoice_doc),
        # "accounting_cost":  sales_invoice_doc.cost_center,
        "buyer_reference": get_icv_code(invoice_number),
        "invoice_period": get_invoice_period(sales_invoice_doc),#wrote a function but incode transaction code list need to check
        "order_reference": {   #OPTIONAL
            "id": "PO-001/23",
            "sales_order_id": "SO-001/23"
        },

        "document_references": {
            
            "invoice_document_reference": {
                "id": str(invoice_number),
                "issue_date": str(sales_invoice_doc.posting_date)
            }
        },
        # "other_references": {
        #     "despatch_document_reference": "DESP-2025-001",
        #     "receipt_document_reference": "REC-2025-001",
        #     "originator_document_reference": "ORIG-2025-001",
        #     "contract_document_reference": {
        #     "id": "CONTRACT-2025-001",
        #     "document_description": "AED 1000000"
        #     },
        #     "customs_document_reference": "CUSTOMS-2025-001",
        #     "project_reference": "PROJECT-2025-001"
        # }, OPTIONAL ORDER REFERENCES
        "receiving_party":receiving_party,

        "invoice_line": [],
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
        "payment_means": [
                {
                "payment_means_code": "55",
                "payment_means_code_name": "Debit Card",
                "card_account": {
                    "primary_account_number_id": "XXXXXXXXXXXX1234",
                    "network_id": "VISA",
                    "holder_name": "Card Holder Name"
                },
                "payee_financial_account": {
                    "id": "AE0000000001",
                    "id_scheme_id": "IBAN",
                    "name": "current account",
                    "financial_institution_branch": {
                    "id": "236000"
                    }
                }
                }
            ],
        "invoice_totals": {}
    }
    exchange_rate = get_currency_exchange_rate(sales_invoice_doc)
    if exchange_rate is not None:
        invoice["currency_exchange_rate"] = exchange_rate

    # Optional accounting_cost at invoice level
    if sales_invoice_doc.get("cost_center"):
        invoice["accounting_cost"] = sales_invoice_doc.cost_center

    # Optional invoice_period
    invoice_period = get_invoice_period(sales_invoice_doc)
    if invoice_period:
        invoice["invoice_period"] = invoice_period

    # # Optional order_reference
    # if getattr(sales_invoice_doc, "custom_order_reference", None):
    #     invoice["order_reference"] = {
    #         "id": sales_invoice_doc.custom_order_reference,
    #         "sales_order_id": getattr(sales_invoice_doc, "sales_order", None)
    #     }
    total_net = Decimal("0")
    total_tax = Decimal("0")

    vat_rate = Decimal(sales_invoice_doc.taxes[0].rate if sales_invoice_doc.taxes else 0)

    invoice_lines_data, total_net, total_tax = get_item_data(sales_invoice_doc, vat_rate)

    # Assign invoice lines to main invoice
    invoice["invoice_line"] = invoice_lines_data["invoice_line"]


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
    Builds UAE invoice JSON, deletes older JSON attachments,
    saves ONLY the latest one, and attaches it to the Sales Invoice.
    """

    invoice_json = build_uae_invoice_json(invoice_number)
    json_content = json.dumps(invoice_json, indent=4, ensure_ascii=False)

    file_name = f"{invoice_number}_uae_invoice.json"

    # 🔥 Delete all previous attachments with same name
    old_files = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Sales Invoice",
            "attached_to_name": invoice_number,
            "file_name": file_name,
        },
        pluck="name",
    )

    for file_name_doc in old_files:
        frappe.delete_doc("File", file_name_doc, force=1)

    # ➕ Create fresh attachment
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
