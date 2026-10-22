"""Fynamics Techno Solutions FZCO adapter (UAE, Peppol 5-corner, PINT AE)."""

import json
from decimal import ROUND_HALF_UP, Decimal
import frappe
import requests
from frappe import _
from frappe.utils import add_days, now_datetime, nowdate, strip_html
from uae_erpgulf.uae_erpgulf.providers.base import BaseAdapter
# Shared PINT-AE helpers and code tables live in providers/pint.py. The
# underscore aliases keep this file's call sites unchanged.
from uae_erpgulf.uae_erpgulf.providers.pint import (
    LEGAL_REGISTRATION_TYPES,
    TWO,
    country_code as _country_code,
    dec as _dec,
    endpoint as _endpoint,
    money as _money,
    num as _num,
    resolve_address_codes,
    split_code as _split_code,
    transaction_type_flags as _transaction_type,
    uom_to_unece_table,
    vat_category_code as _vat_category_code,
)

FYNAMICS_PROVIDER_NAME = "Fynamics Techno Solutions – FZCO"
FYNAMICS_TIMEOUT = 60
API_PREFIX = "/partner/api"
LINE_UNIT_CODE_KEY = "InvoicedUniteCode"

# document status words -> custom_reporting_status
SUCCESS_WORDS = ("SUCCESS", "SUCCESSFUL", "DELIVERED", "ACCEPTED", "REPORTED", "COMPLETED", "DONE")
FAILED_WORDS = ("FAILED", "FAILURE", "ERROR", "REJECTED", "INVALID")
PENDING_WORDS = ("QUEUED", "PROCESSING", "PENDING", "IN_PROGRESS", "SUBMITTED", "RECEIVED")

# Fynamics wants H87 (not EA) for piece-type units.
UOM_TO_UNECE = uom_to_unece_table(piece_code="H87")


# ---------------------------------------------------------------- helpers
def _s(value):
    """Fynamics sends every unused field as an empty string."""
    return "" if value is None else str(value)


def _postal_address(address):
    """Address doc -> Fynamics PostalAddress block."""
    if not address:
        return {
            "StreetName": "", "AdditionalStreetName": "", "CityName": "", "PostalZone": "",
            "AddressLine": "", "CountrySubentity": "", "CountryCode": "",
        }
    country, subentity = resolve_address_codes(address)
    return {
        "StreetName": _s(address.address_line1),
        "AdditionalStreetName": _s(address.address_line2),
        "CityName": _s(address.city),
        "PostalZone": _s(address.pincode),
        "AddressLine": "",
        "CountrySubentity": _s(subentity),
        "CountryCode": country,
    }


def _full_name(contact):
    parts = [contact.get("first_name"), contact.get("last_name")]
    return " ".join(part for part in parts if part)


def _get_address(name):
    return frappe.get_doc("Address", name) if name else None


def _empty_charge(kind):
    reason_key = "ChargeReasonCode" if kind == "Charge" else "AllowanceReasonCode"
    text_key = "ChargeReason" if kind == "Charge" else "AllowanceReason"
    return {
        reason_key: "", text_key: "", "MultiplierFactorNumeric": "", "AmountCurrencyCode": "",
        "AmountValue": "", "BaseAmountCurrencyCode": "", "BaseAmountValue": "",
    }


class FynamicsAdapter(BaseAdapter):
    # No XML / PDF download API in the guide - don't try on submit or in sync.
    AUTO_FETCH_DOCUMENTS_ON_SUBMIT = False
    ATTACH_DOCUMENTS_IN_SYNC = False
    HAS_DOCUMENT_DOWNLOAD = False

    # ---------------------------------------------------------------- auth
    def get_api_url(self):
        """Base URL may be entered with or without /partner/api."""
        base = (self.get_base_url() or "").strip().split("#")[0].rstrip("/")
        if not base:
            frappe.throw(_("Please enter Base URL on E-Invoice Provider Settings."))
        if base.endswith("/docs"):
            base = base[: -len("/docs")]
        if base.startswith("http://"):
            base = "https://" + base[len("http://"):]
        if not base.endswith(API_PREFIX):
            base = f"{base}{API_PREFIX}"
        return base

    def get_valid_token(self):
        """Static token from onboarding: Auth Type "api_key" -> API Key field
        (Client Secret is read too, in case the row is on oauth2)."""
        token = (
            self.settings.get_password("api_key", raise_exception=False)
            or self.settings.get_password("client_secret", raise_exception=False)
            or ""
        ).strip()
        if not token:
            frappe.throw(
                _("Set Auth Type to api_key and put the API token Fynamics issued at onboarding "
                  "in API Key on E-Invoice Provider Settings {0}.").format(self.settings.name)
            )
        return token

    def _fetch_token(self):
        # Static token - nothing to fetch.
        return self.get_valid_token()

    def get_auth_headers(self, extra=None):
        headers = dict(extra or {})
        headers["Authorization"] = f"Bearer {self.get_valid_token()}"
        return headers

    def _request(self, method, path, **kwargs):
        extra = kwargs.pop("headers", None)
        url = f"{self.get_api_url()}{path}"
        response = requests.request(
            method,
            url,
            headers=self.get_auth_headers(extra),
            timeout=FYNAMICS_TIMEOUT,
            allow_redirects=False,
            **kwargs,
        )
        if response.status_code in (301, 302, 303, 307, 308, 405):
            frappe.throw(
                _("Fynamics rejected {0} {1} with HTTP {2}{3}. Check Base URL on E-Invoice Provider "
                  "Settings {4}: it must be https://sandbox-uae.fynamicstax.com (sandbox) or "
                  "https://uae.fynamicstax.com (production), with nothing after it.").format(
                    method, url, response.status_code,
                    (" -> " + response.headers.get("Location", "")) if response.is_redirect else "",
                    self.settings.name,
                )
            )
        return response

    def verify_auth(self):
        """No auth endpoint - list today's received documents; anything
        but 401/403 means the token is accepted."""
        settings = self.settings
        try:
            response = self._request("GET", f"/getDocuments/{nowdate()}")
            ok = response.status_code not in (401, 403)
            settings.db_set("last_test_status", "Passed" if ok else "Failed")
            settings.db_set("last_test_on", now_datetime())
            if ok:
                return {"status": "success", "response": _("Token accepted by Fynamics")}
            return {"status": "error", "message": response.text or _("Token rejected (HTTP {0})").format(
                response.status_code)}
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Fynamics Verify Error")
            settings.db_set("last_test_status", "Failed")
            settings.db_set("last_test_on", now_datetime())
            return {"status": "error", "message": str(e)}

    def get_participant_details(self):
        frappe.throw(_("Fynamics has no participant details API - check your VAT details in the Fynamics portal."))

    def lookup_peppol_id(self, peppol_id):
        frappe.throw(_("Fynamics has no Peppol lookup API."))

    def update_participant(self, company_doc):
        frappe.throw(_("Fynamics participant details are managed in the Fynamics portal."))

    # ------------------------------------------------------------- submit
    def submit_invoice(self, doctype, doc, json_data=None):
        if doctype not in ("Sales Invoice", "Purchase Invoice"):
            frappe.throw(_("Fynamics adapter supports Sales Invoice and Purchase Invoice only."))

        payload = self._build_payload(doctype, doc)
        self.save_outgoing_payload(doc, payload)

        response = self._request(
            "POST", "/invoicerequest", json=payload, headers={"Content-Type": "application/json"}
        )
        try:
            response_data = response.json()
        except Exception:
            response_data = response.text
        return response.status_code, response_data

    def parse_submit_response(self, status_code, response_data):
        body = response_data if isinstance(response_data, dict) else {}
        uuid = _find_uuid(body)
        success = status_code in (200, 201) and bool(uuid)
        return {
            "document_id": uuid,
            "reporting_status": "pending" if success else None,
            "exchange_status": _find_status(body),
            "success": success,
        }

    def _invoice_type_code(self, doctype, doc):
        if doctype == "Purchase Invoice":
            return "261" if doc.is_return else "389"
        out_of_scope = _vat_category_code(doc.get("custom_vat_category")) == "O"
        if doc.is_return:
            return "81" if out_of_scope else "381"
        return "480" if out_of_scope else "380"

    def _issue_time(self, doc):
        t = doc.posting_time
        if not t:
            return ""
        if hasattr(t, "total_seconds"):
            s = int(t.total_seconds())
            return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
        return frappe.utils.get_time(t).strftime("%H:%M:%S")

    def _build_payload(self, doctype, doc):
        type_code = self._invoice_type_code(doctype, doc)
        is_credit = type_code in ("381", "81", "261")
        currency = (doc.currency or "").upper()
        company_currency = (frappe.get_cached_value("Company", doc.company, "default_currency") or "AED").upper()
        conversion_rate = _dec(doc.conversion_rate or 1)

        if doctype == "Purchase Invoice":
            # self-billing: the supplier is the seller, our company the buyer
            supplier_party = self._party_from_supplier(doc)
            customer_party = self._party_from_company(doc, as_seller=False)
        else:
            supplier_party = self._party_from_company(doc, as_seller=True)
            customer_party = self._party_from_customer(doc)

        built = self._build_lines(doc, currency)

        header = {
            "InvoiceNumber": doc.name,
            "IssueDate": str(doc.posting_date),
            "IssueTime": self._issue_time(doc),
            "DueDate": "" if is_credit else _s(doc.get("due_date")),
            "InvoiceTypeCode": type_code,
            "TransactionType": _transaction_type(doc),
            "Note": strip_html(_s(doc.get("custom_invoice_note") or doc.get("remarks"))).strip(),
            "TaxPointDate": str(doc.posting_date),
            "DocumentCurrencyCode": currency,
            "TaxCurrencyCode": company_currency if currency != company_currency else "",
            "AccountingCost": _s(doc.get("cost_center")) if doctype == "Purchase Invoice" else "",
            "InvoicePeriodStartDate": _s(doc.get("from_date")),
            "InvoicePeriodEndDate": _s(doc.get("to_date")),
            "InvoicePeriodDescriptionCode": "",
            "DiscrepancyResponse": "",
        }

        billing_reference = {"ID": "", "IssueDate": ""}
        if is_credit:
            reason_code = self._credit_note_reason(doc)
            header["DiscrepancyResponse"] = reason_code
            if not doc.return_against:
                frappe.throw(_("This return has no Return Against invoice set - Fynamics requires the "
                               "original invoice in BillingReference."))
            original = frappe.get_doc(doctype, doc.return_against)
            billing_reference = {"ID": original.name, "IssueDate": str(original.posting_date)}

        payload = {
            "Invoice": header,
            "BuyerReference": _s(doc.get("po_no")),
            "OrderReference": {"ID": _s(doc.get("po_no")), "SalesOrderID": self._sales_order(doc)},
            "BillingReference": billing_reference,
            "DespatchDocumentReference": "",
            "ReceiptDocumentReference": {"ID": ""},
            "StatementDocumentReference": "",
            "OriginatorDocumentReference": "",
            "ContractDocumentReference": {"ID": "", "DocumentDescription": ""},
            "AdditionalDocumentReference": [{
                "ID": "", "URI": "", "EmbeddedDocumentBinaryObject": "", "filename": "",
                "mimeCode": "", "DocumentTypeCode": "", "DocumentDescription": "",
            }],
            "ProjectReference": {"ID": _s(doc.get("project"))},
            "AccountingSupplierParty": supplier_party,
            "AccountingCustomerParty": customer_party,
            "BuyerCustomerParty": {"PartyIdentificationNumber": ""},
            "SellerSupplierParty": {"PartyIdentificationNumber": ""},
            "TaxRepresentativeParty": {
                "PartyName": "", "PostalAddress": _postal_address(None),
                "PartyTaxCompanyID": "", "PartyTaxCode": "",
            },
            "Delivery": self._delivery(doc),
            "PayeeParty": {"PartyIdentificationCode": "", "PartyIdentificationNumber": "",
                           "PartyName": "", "CompanyID": ""},
            "PaymentMeans": self._payment_means(doctype, doc),
            "PaymentTerms": _s(doc.get("payment_terms_template")),
            "TaxExchangeRate": {
                "SourceCurrencyCode": currency if currency != company_currency else "",
                "TargetCurrencyCode": company_currency if currency != company_currency else "",
                "CalculationRate": _num(conversion_rate) if currency != company_currency else "",
            },
            "TaxTotal": self._tax_total(built, currency, company_currency, conversion_rate),
            "LegalMonetaryTotal": self._monetary_total(doc, built, currency),
            "TotalCharge": [_empty_charge("Charge") | {
                "TaxCategoryID": "", "TaxCategoryPercent": "", "TaxCategoryTaxScheme": ""}],
            "TotalAllowance": built["allowances"] or [_empty_charge("Allowance") | {
                "TaxCategoryID": "", "TaxCategoryPercent": "", "TaxCategoryTaxScheme": ""}],
            "InvoiceReferences": {},
            "InvoiceLine": built["lines"],
        }
        return payload

    def _sales_order(self, doc):
        for item in doc.get("items") or []:
            if item.get("sales_order"):
                return item.sales_order
        return ""

    def _credit_note_reason(self, doc):
        raw = doc.get("custom_credit_note_reason_code")
        if not raw:
            frappe.throw(_("Please select a Credit Note Reason Code before submitting this return."))
        code, _text = _split_code(raw)
        return code

    # ------------------------------------------------------------- parties
    def _legal_entity(self, party_doc, registration_name, required):
        """PartyLegalEntity from the party's own fields:
        custom_legal_registration_identifier_type, custom_trade_license_number,
        custom_legal_registration_authority."""
        number = (party_doc.get("custom_trade_license_number") or "").strip()
        reg_type = party_doc.get("custom_legal_registration_identifier_type")
        if not number:
            if required:
                frappe.throw(
                    _("{0} {1} has no Legal Registration Number ({2}) - Fynamics requires the "
                      "seller's PartyLegalEntity.CompanyID and schemeAgencyID.").format(
                        _(party_doc.doctype), party_doc.name, reg_type or _("Commercial/Trade license"))
                )
            return {"RegistrationName": _s(registration_name), "CompanyID": "",
                    "schemeAgencyID": "", "schemeAgencyName": "", "CompanyLegalForm": ""}

        scheme = LEGAL_REGISTRATION_TYPES.get(reg_type)
        if not scheme:
            frappe.throw(
                _("Set Legal Registration Identifier Type on {0} {1} (Commercial/Trade license, "
                  "Emirates ID, Passport or Cabinet decision).").format(_(party_doc.doctype), party_doc.name)
            )
        return {
            "RegistrationName": _s(registration_name),
            "CompanyID": number,
            "schemeAgencyID": scheme,
            "schemeAgencyName": _s(party_doc.get("custom_legal_registration_authority")),
            "CompanyLegalForm": _s(party_doc.get("custom_company_legal_form")),
        }

    def _contact(self, doc):
        """Invoice contact; falls back to the party's primary contact."""
        name = doc.get("contact_display")
        phone = doc.get("contact_mobile") or doc.get("contact_phone")
        email = doc.get("contact_email")
        contact_name = doc.get("contact_person")
        if not contact_name:
            party_type = "Customer" if doc.doctype == "Sales Invoice" else "Supplier"
            party = doc.get("customer") if party_type == "Customer" else doc.get("supplier")
            contact_name = frappe.db.get_value(party_type, party, f"{party_type.lower()}_primary_contact")
        if contact_name and not (name and (phone or email)):
            contact = frappe.get_cached_doc("Contact", contact_name)
            name = name or _full_name(contact)
            phone = phone or contact.get("mobile_no") or contact.get("phone")
            email = email or contact.get("email_id")
        return {"Name": _s(name), "Telephone": _s(phone), "Email": _s(email)}

    def _company_contact_name(self, doc):
        """Our contact: the invoice's Company Contact Person, else its owner."""
        person = doc.get("company_contact_person")
        if person:
            contact = frappe.get_cached_doc("Contact", person)
            return _full_name(contact)
        return frappe.db.get_value("User", doc.owner, "full_name") if doc.get("owner") else ""

    def _check_trn(self, trn, label):
        trn = (trn or "").strip()
        if not (trn.isdigit() and len(trn) == 15):
            frappe.throw(_("{0}: TRN must be exactly 15 digits, not '{1}'.").format(label, trn))
        return trn

    def _party_from_company(self, doc, as_seller):
        from frappe.contacts.doctype.address.address import get_default_address

        company = frappe.get_doc("Company", doc.company)
        address_name = (
            doc.get("company_address") if doc.doctype == "Sales Invoice" else doc.get("billing_address")
        ) or get_default_address("Company", company.name)
        if not address_name:
            frappe.throw(_("Company {0} has no Address linked to it.").format(company.name))
        address = _get_address(address_name)

        endpoint, scheme = _endpoint(self.settings.participant_id)
        if not (endpoint.isdigit() and len(endpoint) == 10):
            frappe.throw(
                _("Participant ID (Peppol) on E-Invoice Provider Settings {0} must be your 10-digit "
                  "TIN, not '{1}'.").format(self.settings.name, self.settings.participant_id)
            )
        trn = self._check_trn(
            self.settings.get("trn") or doc.get("company_tax_id") or company.tax_id,
            _("Company {0}").format(company.name),
        )
        party = {
            "schemeID": scheme,
            "EndpointID": endpoint,
            "PartyIdentificationCode": scheme,
            "PartyIdentificationNumber": trn,
            "PartyName": company.company_name,
            "PostalAddress": _postal_address(address),
            "PartyTaxCompanyID": trn,
            "PartyTaxCode": "VAT",
            "PartyLegalEntity": self._legal_entity(company, company.company_name, required=as_seller),
            "Contact": {
                "Name": _s(self._company_contact_name(doc)),
                "Telephone": _s(address.phone or company.get("phone_no")),
                "Email": _s(address.email_id or company.get("email")),
            },
        }
        return party

    def _party_from_customer(self, doc):
        customer = frappe.get_doc("Customer", doc.customer)
        address = _get_address(doc.get("customer_address") or customer.get("customer_primary_address"))
        if not address:
            frappe.throw(_("Customer address not found for {0}").format(doc.customer))
        peppol_id = customer.get("custom_peppol_id")
        if not peppol_id:
            frappe.throw(_("Customer {0} has no Peppol ID set.").format(doc.customer))
        endpoint, scheme = _endpoint(peppol_id)
        trn = self._check_trn(doc.get("tax_id") or customer.tax_id, _("Customer {0}").format(doc.customer))
        name = doc.get("customer_name") or customer.customer_name
        return {
            "schemeID": scheme,
            "EndpointID": endpoint,
            "PartyIdentificationCode": scheme,
            "PartyIdentificationNumber": trn,
            "PartyName": name,
            "PostalAddress": _postal_address(address),
            "PartyTaxCompanyID": trn,
            "PartyTaxCode": "VAT",
            "PartyLegalEntity": self._legal_entity(customer, name, required=False),
            "Contact": self._contact(doc),
        }

    def _party_from_supplier(self, doc):
        supplier = frappe.get_doc("Supplier", doc.supplier)
        address = _get_address(doc.get("supplier_address") or supplier.get("supplier_primary_address"))
        if not address:
            frappe.throw(_("Supplier address not found for {0}").format(doc.supplier))
        peppol_id = supplier.get("custom_peppol_id")
        if not peppol_id:
            frappe.throw(_("Supplier {0} has no Peppol ID set.").format(doc.supplier))
        endpoint, scheme = _endpoint(peppol_id)
        trn = self._check_trn(doc.get("tax_id") or supplier.tax_id, _("Supplier {0}").format(doc.supplier))
        name = doc.get("supplier_name") or supplier.supplier_name
        return {
            "schemeID": scheme,
            "EndpointID": endpoint,
            "PartyIdentificationCode": scheme,
            "PartyIdentificationNumber": trn,
            "PartyName": name,
            "PostalAddress": _postal_address(address),
            "PartyTaxCompanyID": trn,
            "PartyTaxCode": "VAT",
            # self-billing: the supplier is the seller, so its registration is required
            "PartyLegalEntity": self._legal_entity(supplier, name, required=True),
            "Contact": self._contact(doc),
        }

    def _delivery(self, doc):
        shipping = doc.get("shipping_address_name") if doc.doctype == "Sales Invoice" else doc.get("shipping_address")
        address = _get_address(shipping)
        # goods leave stock with this invoice -> delivered on the posting date
        delivered = _s(doc.posting_date) if doc.get("update_stock") else ""
        return {
            "ActualDeliveryDate": delivered,
            "DeliveryLocationSchemeID": "",
            "DeliveryLocationValue": "",
            "PostalAddress": _postal_address(address),
            "DeliveryPartyID": "",
            "DeliveryPartyName": _s(address.get("address_title")) if address else "",
            "DeliveryTermschemeID": "",
            "DeliveryTermValue": "",
        }

    # ------------------------------------------------------------- payment
    def _payment_means(self, doctype, doc):
        """Purchase Invoice: its own Payment Means Codes field. Sales Invoice:
        that field, else the code on the first Mode of Payment used."""
        raw = doc.get("custom_payment_means_codes")
        if not raw and doctype == "Sales Invoice":
            for row in doc.get("payments") or []:
                if row.mode_of_payment:
                    raw = frappe.get_cached_value("Mode of Payment", row.mode_of_payment, "custom_payment_means_codes")
                    if raw:
                        break
        if not raw:
            frappe.throw(_("Set a Payment Means Code on {0} (or on its Mode of Payment) - Fynamics "
                           "requires PaymentMeansCode.").format(doc.name))
        code, text = _split_code(raw)

        account = {"ID": "", "AccountNumber": "", "Name": "", "BranchID": "", "PostalAddress": _postal_address(None)}
        bank_account = doc.get("company_bank_account") if doctype == "Sales Invoice" else doc.get("supplier_bank_account")
        if not bank_account and doctype == "Sales Invoice":
            bank_account = frappe.db.get_value(
                "Bank Account", {"company": doc.company, "is_company_account": 1, "is_default": 1}, "name"
            )
        if bank_account:
            bank = frappe.get_cached_doc("Bank Account", bank_account)
            account.update({
                "ID": _s(bank.get("iban")),
                "AccountNumber": _s(bank.get("bank_account_no")),
                "Name": _s(bank.get("account_name")),
                "BranchID": _s(bank.get("branch_code")),
            })

        return {
            "PaymentID": "",
            "PaymentMeansCode": code,
            "PaymentMeansName": text if text != code else "",
            "PaymentDueDate": _s(doc.get("due_date")),
            "CardAccount": {"PrimaryAccountNumberID": "", "NetworkID": "", "HolderName": ""},
            "PayeeFinancialAccount": account,
            "PaymentMandate": "",
        }

    # --------------------------------------------------------------- lines
    def _item_tax(self, doc, item):
        category = doc.get("custom_vat_category")
        rate = doc.taxes[0].rate if doc.get("taxes") else 0
        if item.get("item_tax_template"):
            template = frappe.get_cached_doc("Item Tax Template", item.item_tax_template)
            category = template.get("custom_vat_category") or category
            if template.taxes:
                rate = template.taxes[0].tax_rate
        if not category:
            frappe.throw(_("Set a VAT Category on {0} or on Item {1}'s Item Tax Template.").format(
                doc.name, item.item_code))
        code = _vat_category_code(category)
        # guide: percent must be 5 for S and 0 for every other category
        if code == "S" and not _dec(rate):
            frappe.throw(
                _("{0} is Standard rated (S) but has no VAT row - add the 5% VAT Sales Taxes and "
                  "Charges Template (or an Item Tax Template on {1}).").format(doc.name, item.item_code)
            )
        rate = _dec(rate) if code == "S" else Decimal("0")
        return code, rate

    def _unit_code(self, uom):
        uom = (uom or "").strip()
        if uom and frappe.get_meta("UOM").has_field("custom_unece_code"):
            code = frappe.get_cached_value("UOM", uom, "custom_unece_code")
            if code:
                return code.strip().upper()
        return UOM_TO_UNECE.get(uom.lower(), uom.upper() or "H87")

    def _item_extra(self, item):
        """Origin country, item type and HS code from the Item / line fields."""
        extra = {"OriginCountryCode": "", "CommodityCode": "", "CommoditylistID": "", "CommoditylistValue": ""}
        if item.get("item_code"):
            origin = frappe.get_cached_value("Item", item.item_code, "country_of_origin")
            extra["OriginCountryCode"] = _s(_country_code(origin))
        item_type = (item.get("custom_item_type_codes") or "").split(" - ")[0].strip().upper()
        if item_type:
            extra["CommodityCode"] = item_type
        if item.get("custom_hs_code_"):
            extra["CommoditylistID"] = "HS"
            extra["CommoditylistValue"] = item.custom_hs_code_
        return extra

    def _build_lines(self, doc, currency):
        """Lines carry the amount before the invoice-level discount; that
        discount (amount - net_amount) goes out as TotalAllowance rows per VAT
        category. Tax-inclusive invoices send net values."""
        tax_inclusive = any(t.get("included_in_print_rate") for t in (doc.get("taxes") or []))
        lines, allowances, breakdown = [], {}, {}
        line_total = Decimal("0")

        for idx, item in enumerate(doc.get("items") or [], 1):
            vat_code, rate = self._item_tax(doc, item)
            qty = abs(_dec(item.qty))
            net_amount = abs(_dec(item.net_amount)).quantize(TWO, ROUND_HALF_UP)
            amount = net_amount if tax_inclusive else abs(_dec(item.amount)).quantize(TWO, ROUND_HALF_UP)
            price = (amount / qty).quantize(TWO, ROUND_HALF_UP) if qty else Decimal("0")
            line_tax = (amount * rate / 100).quantize(TWO, ROUND_HALF_UP)
            unit = self._unit_code(item.get("uom"))
            line_total += amount

            item_block = {
                "Description": strip_html(item.get("description") or "").strip() or item.item_name,
                "Name": (item.item_name or "")[:100],
                "BuyersItemID": _s(item.get("customer_item_code")),
                "SellersItemID": _s(item.get("item_code")),
                "StandardItemValue": _s(item.get("barcode")),
            }
            item_block.update(self._item_extra(item))
            item_block.update({
                "TaxCategoryID": vat_code,
                "TaxCategoryPercent": _num(rate),
                "TaxCategorySchemeID": "VAT",
                "AdditionalItemProperty": {"Name": "", "Value": ""},
            })

            lines.append({
                "ID": str(item.get("idx") or idx),
                "Note": "",
                "InvoicedQuantity": _num(qty),
                LINE_UNIT_CODE_KEY: unit,
                "LineExtensionAmount": _money(amount),
                "LineExtensionAmountCurrencyCode": currency,
                "AccountingCost": _s(item.get("cost_center")) if doc.doctype == "Purchase Invoice" else "",
                "InvoicePeriodStartDate": "",
                "InvoicePeriodEndDate": "",
                "OrderLineReferenceID": "",
                "OrderLineReferenceValue": _s(item.get("purchase_order")),
                "Charge": [_empty_charge("Charge")],
                "Allowance": [_empty_charge("Allowance")],
                "Item": item_block,
                "Price": {
                    "PriceAmount": _money(price),
                    "PriceAmountCurrencyCode": currency,
                    "BaseQuantity": "1",
                    "BaseUnitCode": unit,
                    "AllowanceChargeIndicator": "",
                    "AllowanceChargeAmountCurrencyCode": "",
                    "AllowanceChargeAmountValue": "",
                    "AllowanceChargeBaseAmountCurrencyCode": "",
                    "AllowanceChargeBaseAmountValue": "",
                },
                "ItemPriceExtension": {
                    "Amount": _money(amount),
                    "CurrencyCode": currency,
                    "TaxAmount": _money(line_tax),
                    "TaxAmountCurrencyCode": currency,
                },
                "InvoiceReferences": {},
            })

            key = (vat_code, rate)
            breakdown[key] = breakdown.get(key, Decimal("0")) + net_amount
            discount = amount - net_amount
            if discount:
                allowances[key] = allowances.get(key, Decimal("0")) + discount

        doc_vat = abs(_dec(doc.get("total_taxes_and_charges"))).quantize(TWO, ROUND_HALF_UP)
        subtotals, vat_total = [], Decimal("0")
        keys = list(breakdown)
        for i, key in enumerate(keys):
            vat_code, rate = key
            tax = (breakdown[key] * rate / 100).quantize(TWO, ROUND_HALF_UP)
            if i == len(keys) - 1 and doc_vat and abs(doc_vat - (vat_total + tax)) < Decimal("1"):
                tax = doc_vat - vat_total
            vat_total += tax
            subtotals.append({
                "TaxableAmount": _money(breakdown[key]),
                "TaxableAmountCurrencyCode": currency,
                "TaxAmount": _money(tax),
                "TaxAmountCurrencyCode": currency,
                "TaxCategoryID": vat_code,
                "TaxCategoryPercent": _num(rate),
                "TaxCategorySchemeID": "VAT",
            })

        allowance_rows = [
            {
                "AllowanceReasonCode": "95",
                "AllowanceReason": _("Discount"),
                "MultiplierFactorNumeric": "",
                "AmountCurrencyCode": currency,
                "AmountValue": _money(amount),
                "TaxCategoryID": vat_code,
                "TaxCategoryPercent": _num(rate),
                "TaxCategoryTaxScheme": "VAT",
                "BaseAmountCurrencyCode": "",
                "BaseAmountValue": "",
            }
            for (vat_code, rate), amount in allowances.items()
        ]

        return {
            "lines": lines,
            "allowances": allowance_rows,
            "subtotals": subtotals,
            "line_total": line_total,
            "allowance_total": sum(allowances.values(), Decimal("0")),
            "vat_total": vat_total,
        }

    def _tax_total(self, built, currency, company_currency, conversion_rate):
        foreign = currency != company_currency
        return {
            "TaxIncludedIndicator": "false",  # every amount sent is VAT-exclusive
            "TaxAmount": _money(built["vat_total"]),
            "TaxAmountCurrencyCode": currency,
            "DocumentTaxAmount": _money(built["vat_total"] * conversion_rate),
            "DocumentTaxAmountCurrencyCode": company_currency,
            "DocumentTaxSubtotal": built["subtotals"],
        }

    def _monetary_total(self, doc, built, currency):
        line_total = built["line_total"]
        allowance_total = built["allowance_total"]
        exclusive = line_total - allowance_total
        inclusive = exclusive + built["vat_total"]

        rounding = _dec(doc.get("rounding_adjustment"))
        if doc.get("is_return"):
            rounding = -rounding
        if doc.get("is_pos"):
            prepaid = abs(_dec(doc.get("paid_amount"))) - abs(_dec(doc.get("change_amount")))
        else:
            prepaid = abs(_dec(doc.get("total_advance")))
        payable = inclusive - prepaid + rounding

        def amount(value, show):
            return (_money(value), currency) if show else ("", "")

        allowance, allowance_cur = amount(allowance_total, allowance_total)
        prepaid_v, prepaid_cur = amount(prepaid, prepaid)
        rounding_v, rounding_cur = amount(rounding, rounding)
        return {
            "LineExtensionAmount": _money(line_total),
            "LineExtensionAmountCurrencyCode": currency,
            "TaxExclusiveAmount": _money(exclusive),
            "TaxExclusiveAmountCurrencyCode": currency,
            "TaxInclusiveAmount": _money(inclusive),
            "TaxInclusiveAmountCurrencyCode": currency,
            "AllowanceTotalAmount": allowance,
            "AllowanceTotalAmountCurrencyCode": allowance_cur,
            "ChargeTotalAmount": "",
            "ChargeTotalAmountCurrencyCode": "",
            "PrepaidAmount": prepaid_v,
            "PrepaidAmountCurrencyCode": prepaid_cur,
            "PayableRoundingAmount": rounding_v,
            "PayableRoundingAmountCurrencyCode": rounding_cur,
            "PayableAmount": _money(payable),
            "PayableAmountCurrencyCode": currency,
        }

    # -------------------------------------------------------------- status
    def _document_id(self, doc):
        document_id = doc.get("custom_document_id")
        if not document_id and doc.get("custom_submit_response"):
            try:
                document_id = _find_uuid(json.loads(doc.custom_submit_response))
            except Exception:
                document_id = None
        if not document_id:
            frappe.throw(_("Fynamics UUID not found on {0} - it hasn't been submitted successfully.").format(doc.name))
        return document_id

    def get_document_status(self, doctype, doc):
        response = self._request("GET", f"/getDocumentStatus/{self._document_id(doc)}")
        try:
            body = response.json()
        except Exception:
            body = response.text
        result = {"http_status": response.status_code, "response": body}
        status = self.get_status_from_document_status(body)
        if status:
            result["reporting_status"] = status
        return result

    def get_status_from_document_status(self, body):
        """QUEUED / PROCESSING -> pending; FAILED (or C2 errors) -> failed;
        SUCCESS -> reported once C5 confirms (or when no C5 detail is given)."""
        if not isinstance(body, (dict, list)):
            return None
        overall = (_find_status(body) or "").upper()
        c5 = (_find_stage_status(body, "c5") or "").upper()

        if any(w in overall for w in FAILED_WORDS) or any(w in c5 for w in FAILED_WORDS):
            return "failed"
        if c5:
            if any(w in c5 for w in SUCCESS_WORDS):
                return "reported"
            return "pending"
        if any(w in overall for w in SUCCESS_WORDS):
            return "reported"
        if any(w in overall for w in PENDING_WORDS):
            return "pending"
        return None

    def get_document_xml(self, doctype, doc):
        frappe.throw(_("Fynamics has no XML download API in its documentation yet."))

    def get_document_pdf(self, doctype, doc):
        frappe.throw(_("Fynamics has no PDF download API in its documentation yet."))

    # ------------------------------------------------------------ webhooks
    def _no_webhook_message(self):
        return _(
            "Fynamics has no webhook API in its documentation. Status is checked automatically "
            "(right after submit and every 5 minutes), and received invoices are pulled every hour."
        )

    def register_webhook(self):
        frappe.throw(self._no_webhook_message())

    def get_subscription(self):
        frappe.throw(self._no_webhook_message())

    def get_webhook_deliveries(self):
        frappe.throw(self._no_webhook_message())

    def get_webhook_listener_url(self):
        # No webhooks: settings save leaves Webhook URL blank. Must not
        # frappe.throw here - saving the settings row calls this.
        return None

    # --------------------------------------------------------- incoming
    def list_received_documents(self, date):
        response = self._request("GET", f"/getDocuments/{date}")
        if response.status_code == 404:
            return []
        if response.status_code != 200:
            frappe.throw(_("Fynamics API Error ({0}): {1}").format(response.status_code, response.text))
        body = response.json()
        if isinstance(body, dict):
            body = body.get("data") or body.get("documents") or body.get("Documents") or []
        uuids = []
        for row in body or []:
            uuid = row if isinstance(row, str) else _find_uuid(row)
            if uuid:
                uuids.append(uuid)
        return uuids

    def get_received_document(self, uuid):
        response = self._request("GET", f"/getDocuments/{uuid}")
        if response.status_code != 200:
            frappe.throw(_("Fynamics API Error ({0}): {1}").format(response.status_code, response.text))
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("data"), dict):
            body = body["data"]
        return body

    def parse_incoming_invoice(self, invoice_json):
        """A received invoice in Fynamics' own JSON shape (same as submit)."""
        if not isinstance(invoice_json, dict):
            return {}
        header = invoice_json.get("Invoice") if isinstance(invoice_json.get("Invoice"), dict) else {}
        seller = invoice_json.get("AccountingSupplierParty")
        lines_json = invoice_json.get("InvoiceLine")
        if not isinstance(seller, dict) or not isinstance(lines_json, list):
            return {}

        unece_to_uom = {}
        for uom, code in UOM_TO_UNECE.items():
            unece_to_uom.setdefault(code, uom.title())
        unece_to_uom["H87"] = "Nos"

        lines = []
        for line in lines_json:
            item = line.get("Item") or {}
            price = line.get("Price") or {}
            qty = float(line.get("InvoicedQuantity") or 1)
            base_qty = float(price.get("BaseQuantity") or 1)
            rate = float(price.get("PriceAmount") or 0) / (base_qty or 1)
            unit = line.get("InvoicedUnitCode") or line.get("InvoicedUniteCode")
            lines.append({
                "name": item.get("Name"),
                "description": item.get("Description"),
                "qty": qty,
                "uom": unece_to_uom.get(unit, unit or "Nos"),
                "rate": rate,
                "amount": float(line.get("LineExtensionAmount") or qty * rate),
                "vat_rate": float(item.get("TaxCategoryPercent") or 0),
            })

        payment = invoice_json.get("PaymentMeans") or {}
        if isinstance(payment, list):
            payment = payment[0] if payment else {}
        rate_block = invoice_json.get("TaxExchangeRate") or {}
        return {
            "supplier_name": seller.get("PartyName"),
            "vat_number": seller.get("PartyTaxCompanyID"),
            "posting_date": header.get("IssueDate"),
            "due_date": header.get("DueDate") or None,
            "currency": header.get("DocumentCurrencyCode"),
            "document_id": invoice_json.get("uuid") or invoice_json.get("UUID") or header.get("InvoiceNumber"),
            "conversion_rate": rate_block.get("CalculationRate") or None,
            "payment_means_code": payment.get("PaymentMeansCode"),
            "lines": lines,
        }


# ------------------------------------------------- response parsing
def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk(value)


def _find_uuid(body):
    """The submit / list response's UUID, whatever the key's case or nesting."""
    if isinstance(body, str):
        return body.strip() or None
    for node in _walk(body):
        for key, value in node.items():
            if key.lower() in ("uuid", "documentuuid", "document_uuid", "documentid", "document_id", "id") \
                    and isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _find_status(body):
    for node in _walk(body):
        for key, value in node.items():
            if key.lower() in ("status", "documentstatus", "document_status") and isinstance(value, str):
                return value
    return None


def _find_stage_status(body, stage):
    """Status of one corner (e.g. 'c5'): a key like c5Status / C5_status, or
    a {'status': ...} block under a key that contains the stage name."""
    stage = stage.lower()
    for node in _walk(body):
        for key, value in node.items():
            k = key.lower()
            if stage not in k:
                continue
            if isinstance(value, str) and "status" in k:
                return value
            if isinstance(value, dict):
                found = _find_status(value)
                if found:
                    return found
    return None


# ------------------------------------------- received invoices (pull)
def fetch_fynamics_incoming_invoices(days_back=1):
    """Scheduled hourly (hooks.py): for every enabled Fynamics settings row,
    list documents received today and yesterday and keep each new one in
    UAE Incoming Invoices, so "Get FTA Incoming Invoices" can import it."""
    rows = frappe.get_all(
        "E-Invoice Provider Settings",
        filters={"provider": FYNAMICS_PROVIDER_NAME, "enabled": 1},
        pluck="name",
    )
    for settings_name in rows:
        adapter = FynamicsAdapter(frappe.get_doc("E-Invoice Provider Settings", settings_name))
        for offset in range(int(days_back), -1, -1):
            date = add_days(nowdate(), -offset)
            try:
                uuids = adapter.list_received_documents(date)
            except Exception:
                frappe.log_error(frappe.get_traceback(), f"Fynamics Incoming List Error - {date}")
                continue
            for uuid in uuids:
                if frappe.db.exists("UAE Incoming Invoices", {"document_id": uuid}):
                    continue
                try:
                    body = adapter.get_received_document(uuid)
                    file_doc = frappe.get_doc({
                        "doctype": "File",
                        "file_name": f"{uuid}_fynamics_incoming.json",
                        "is_private": 1,
                        "content": json.dumps(body, indent=2),
                    }).insert(ignore_permissions=True)
                    frappe.get_doc({
                        "doctype": "UAE Incoming Invoices",
                        "document_id": uuid,
                        "incoming_invoice_file": file_doc.file_url,
                        "status": "Not Submitted",
                        "submit_response": json.dumps(body),
                    }).insert(ignore_permissions=True)
                    frappe.db.commit()  # nosemgrep: frappe-manual-commit
                except Exception:
                    frappe.db.rollback()
                    frappe.log_error(frappe.get_traceback(), f"Fynamics Incoming Fetch Error - {uuid}")
