"""Marmin AI Software Design LLC adapter."""

import base64
import hmac
import hashlib
import json

import frappe
import requests
from frappe import _
from datetime import timedelta
from uae_erpgulf.uae_erpgulf.providers.base import BaseAdapter
from uae_erpgulf.uae_erpgulf.country_code import country_code_mapping



def _marmin_uae_emirate_code(emirate_name):
    """Full UAE emirate name -> PEPPOL subdivision code"""
    if not emirate_name:
        return None

    mapping = {
        "abu dhabi": "AUH",
        "dubai": "DXB",
        "sharjah": "SHJ",
        "ajman": "AJM",
        "umm al quwain": "UAQ",
        "ras al khaimah": "RAK",
        "fujairah": "FUJ",
    }

    return mapping.get(emirate_name.strip().lower())


def _marmin_vat_category_code(vat_category_label):
    """VAT category label (e.g. "S - Standard Rated") -> PEPPOL VAT category
    code (S, Z, E, AE, O, N). Identical mapping to json_einvoice.py's own
    get_vat_category_code - copied in, not imported."""
    if not vat_category_label:
        return None

    mapping = {
        "s - standard rated": "S", "standard rated": "S", "s": "S",
        "z - zero rated": "Z", "zero rated": "Z", "z": "Z",
        "e - exempt from tax": "E", "exempt from tax": "E", "e": "E",
        "ae - vat reverse charge": "AE", "vat reverse charge": "AE",
        "reverse charge": "AE", "ae": "AE",
        "o - not subject to vat": "O", "not subject to vat": "O", "o": "O",
        "n - margin scheme": "N", "margin scheme": "N", "n": "N",
    }

    code = mapping.get(vat_category_label.strip().lower())
    if not code:
        frappe.throw(
            _(
                "Invalid VAT Category: {0}. Must be one of S, Z, E, AE, O, N."
            ).format(vat_category_label)
        )
    return code


def _marmin_sales_invoice_type_code(doc):
    """Sales Invoice invoice_type_code, same rule json_einvoice.py's own
    get_invoice_type_code uses: "381" for a return, "480" """
    if doc.is_return == 1:
        return "381"
    if doc.is_return == 1 and doc.custom_vat_category == "O - Not subject to VAT":
        return "81"
    if doc.custom_vat_category == "O - Not subject to VAT":
        return "480"
    return "380"


def _marmin_purchase_invoice_type_code(doc):
    """Purchase Invoice invoice_type_code, same rule purchase_json.py's own
    get_invoice_type_code uses: "361" for a return, else "389"."""
    if doc.is_return == 1:
        return "361"
    return "389"


def _marmin_issue_time(doc):
    """posting_time -> "HH:MM:SS" string."""
    issue_time = doc.posting_time
    if not issue_time:
        return None
    if isinstance(issue_time, timedelta):
        total_seconds = int(issue_time.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    if isinstance(issue_time, str):
        return frappe.utils.get_time(issue_time).strftime("%H:%M:%S")
    return issue_time.strftime("%H:%M:%S")


def _marmin_sales_payment_means(doc):
    """Sales Invoice payment_means, built from this invoice's own Payments
    table -> Mode of Payment -> Accounts"""
    payment_means_list = []

    for pay_row in doc.payments or []:
        if not pay_row.mode_of_payment:
            continue

        mop = frappe.get_doc("Mode of Payment", pay_row.mode_of_payment)
        pm_code = mop.get("custom_payment_means_codes") or ""
        payment_code = ""
        payment_option = ""
        if pm_code and " - " in pm_code:
            payment_code, payment_option = pm_code.split(" - ", 1)
        if not mop.accounts:
            continue

        mop_acc = mop.accounts[0]
        acc = frappe.get_doc("Account", mop_acc.default_account)

        payment_means_entry = {
            "payment_means_code": payment_code,
            "payment_means_code_name": payment_option,
            "payee_financial_account": {
                "id": acc.account_number,
                "id_scheme_id": "IBAN" if acc.account_type == "Bank" else "OTH",
                "name": acc.account_name,
                "financial_institution_branch": {
                    "id": acc.company or ""
                },
            },
        }

        if payment_code in ["48", "55", "57"]:
            payment_means_entry["card_account"] = {
                "primary_account_number_id": "XXXXXXXXXXXX1234",
                "network_id": "VISA",
                "holder_name": doc.customer,
            }

        payment_means_list.append(payment_means_entry)

    return payment_means_list

MARMIN_API_VERSION = "20260507"  # from the 2026-05-07 docs page
MARMIN_PROFILE_EXECUTION_ID_STANDARD = "00000000"
MARMIN_DEFAULT_PAYMENT_MEANS_CODE = "1"
MARMIN_APPROVED_PAYMENT_MEANS_CODES = {"1", "10", "20", "21", "30", "49", "54", "55", "68"}


MARMIN_ENDPOINT_SCHEME_ID_UAE = "0235"
MARMIN_UOM_TO_UNECE_CODE = {
    "nos": "EA", "unit": "EA", "each": "EA", "pcs": "EA", "piece": "EA",
    "kg": "KGM", "kilogram": "KGM",
    "gram": "GRM", "gm": "GRM",
    "litre": "LTR", "liter": "LTR", "ltr": "LTR",
    "meter": "MTR", "metre": "MTR", "mtr": "MTR",
    "box": "BX",
    "pair": "PR",
    "dozen": "DZN",
    "hour": "HUR",
    "day": "DAY",
}


class MarminAdapter(BaseAdapter):

    DOCUMENT_FETCH_RETRY_ATTEMPTS = 3
    DOCUMENT_FETCH_RETRY_DELAY_SECONDS = 5

    # ---- auth ----
    def get_auth_headers(self, extra=None):
        headers = dict(extra or {})
        headers["Authorization"] = f"Bearer {self.get_valid_token()}"
        headers["X-MARMIN-VERSION"] = MARMIN_API_VERSION
        return headers

    def _fetch_token(self):
        settings = self.settings
        base_url = self.get_base_url()
        client_id = settings.client_id
        client_secret = settings.get_password("client_secret")

        if not base_url or not client_id or not client_secret:
            frappe.throw(
                _("Please enter Base URL, Client ID and Client Secret on E-Invoice Provider Settings.")
            )

        # HMAC-SHA256(key=client_secret, message=client_id), base64-encoded -
        # exactly the signature Marmin's token endpoint expects in
        # x-marmin-signature.
        signature = base64.b64encode(
            hmac.new(
                client_secret.encode("utf-8"),
                client_id.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")

        url = f"{base_url}/auth/token"
        headers = {
            "x-marmin-signature": signature,
            "X-MARMIN-VERSION": MARMIN_API_VERSION,
        }

        response = requests.get(url, params={"client_id": client_id}, headers=headers)

        if not response.ok:
            frappe.throw(
                _("Marmin token request failed ({0}): {1}").format(
                    response.status_code, response.text
                )
            )

        try:
            response_json = response.json()
        except Exception:
            frappe.throw(_("Marmin token response wasn't JSON: {0}").format(response.text))

        access_token = (
            response_json.get("access_token")
            or response_json.get("token")
            or response_json.get("data", {}).get("access_token")
        )

        if not access_token:
            frappe.throw(
                _("Access token not found in Marmin token response: {0}").format(response_json)
            )
        expires_in = response_json.get("expires_in") or response_json.get("data", {}).get(
            "expires_in"
        )
        if isinstance(expires_in, (int, float)) and expires_in > 0:
            self.set_cached_token(access_token, expires_in_sec=int(expires_in))
        else:
            self.set_cached_token(access_token)

        return access_token

    # ---- not yet backed by a verified docs page ----
    def verify_auth(self):
        frappe.throw(_("Marmin auth verification isn't implemented yet - no docs page for it."))

    def get_participant_details(self):
        """GET /api/business-profiles/{profileId}"""
        settings = self.settings
        business_profile_id = settings.participant_id
        if not business_profile_id:
            frappe.throw(
                _(
                    "Business Profile ID (stored in Participant ID) is missing on "
                    "E-Invoice Provider Settings"
                )
            )

        base_url = self.get_base_url()
        url = f"{base_url}/api/business-profiles/{business_profile_id}"
        headers = self.get_auth_headers()

        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return {"status": "success", "response": response.json()}

        frappe.throw(_("Marmin API Error: {0}").format(response.text))

    def lookup_peppol_id(self, peppol_id):
        frappe.throw(_("Marmin PEPPOL lookup isn't implemented yet - no docs page for it."))

    def update_participant(self, company_doc):
        frappe.throw(_("Marmin participant update isn't implemented yet - no docs page for it."))

    def _document_resource_path(self, doc):
        """"sales-invoices", "sales-credit-notes", or purchas invoice"""
        if doc.doctype == "Purchase Invoice":
            return "purchase-invoices"
        return "sales-credit-notes" if doc.is_return else "sales-invoices"

    def get_document_status(self, doctype, doc):
        """GET /api/sales-invoices/{id}/peppol-status-logs """
        if not doc.custom_submit_response:
            frappe.throw(_("Submit response not found in Invoice"))

        response_data = json.loads(doc.custom_submit_response)
        document_id = response_data.get("id") or response_data.get("data", {}).get("id")
        if not document_id:
            frappe.throw(_("Marmin invoice id not found in submit response"))

        base_url = self.get_base_url()
        resource = self._document_resource_path(doc)
        url = f"{base_url}/api/{resource}/{document_id}/peppol-status-logs"
        headers = self.get_auth_headers()

        response = requests.get(url, headers=headers)
        try:
            body = response.json()
        except Exception:
            body = response.text

        result = {"http_status": response.status_code, "response": body}

        
        if isinstance(body, list):
            derived = self._reporting_status_from_status_logs(body)
            if derived:
                result["reporting_status"] = derived

        return result

    @staticmethod
    def _reporting_status_from_status_logs(events):
        """Best-effort derivation of a reporting_status from Marmin's
        peppol-status-logs event list."""
        if not isinstance(events, list) or not events:
            return None
        try:
            events = sorted(events, key=lambda e: e.get("timestamp") or 0)
        except Exception:
            pass

        haystack = " ".join(
            f"{e.get('event') or ''} {e.get('message') or ''}"
            for e in events
            if isinstance(e, dict)
        ).lower()

        if any(k in haystack for k in ("fail", "reject", "error", "invalid")):
            return "failed"

        # Confirmed case: the FTA (C5) sent back a Message Level Status.
        if "mls_received_from_c5" in haystack or "received mls from c5" in haystack:
            return "reported"

    
        if "to_c5" in haystack or "to c5" in haystack:
            return "pending"

        return "not reported"

    def get_document_xml(self, doctype, doc):
        """GET /api/sales-invoices/{id}/xml - confirmed docs page """
        if not doc.custom_submit_response:
            frappe.throw(_("Submit response not found in Invoice"))

        response_data = json.loads(doc.custom_submit_response)
        document_id = response_data.get("id") or response_data.get("data", {}).get("id")
        if not document_id:
            frappe.throw(_("Marmin invoice id not found in submit response"))

        base_url = self.get_base_url()
        resource = self._document_resource_path(doc)
        url = f"{base_url}/api/{resource}/{document_id}/xml"
        headers = self.get_auth_headers()

        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.text

        frappe.throw(_("Marmin API Error: {0}").format(response.text))

    def get_document_pdf(self, doctype, doc):
        """GET /api/sales-invoices/{id}/download-pdf """
        if not doc.custom_submit_response:
            frappe.throw(_("Submit response not found in Invoice"))

        response_data = json.loads(doc.custom_submit_response)
        document_id = response_data.get("id") or response_data.get("data", {}).get("id")
        if not document_id:
            frappe.throw(_("Marmin invoice id not found in submit response"))

        base_url = self.get_base_url()
        resource = self._document_resource_path(doc)
        url = f"{base_url}/api/{resource}/{document_id}/download-pdf"
        headers = self.get_auth_headers()

        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.content

        frappe.throw(_("Marmin API Error: {0}").format(response.text))

   
    _WEBHOOK_NOT_AN_API_MESSAGE = _(
        "Marmin doesn't have a webhook subscription API - it's configured only "
        "in the Marmin Web Application (Developer Dashboard > Webhooks tab), "
        "gated by an OTP sent to your email. To set it up: paste this row's "
        "Webhook URL into that dashboard as the endpoint, then Reveal/Regenerate "
        "the Webhook Signing Secret there and paste it into this row's Webhook "
        "Secret field. There's nothing to click here for that - Subscribe "
        "Webhook / Get Subscription / Webhook Logs only exist for providers "
        "(like Flick) that expose an actual API for it."
    )

    def register_webhook(self):
        frappe.throw(self._WEBHOOK_NOT_AN_API_MESSAGE)

    def get_subscription(self):
        frappe.throw(self._WEBHOOK_NOT_AN_API_MESSAGE)

    def get_webhook_deliveries(self):
        frappe.throw(self._WEBHOOK_NOT_AN_API_MESSAGE)

    def get_webhook_listener_url(self):
        """The URL to paste into Marmin's Developer Dashboard > Webhooks"""
        return frappe.utils.get_url(
            "/api/method/uae_erpgulf.uae_erpgulf.providers.marmin.adapter.marmin_webhook_listener"
        )

    # ---- invoices: the one thing we do have real docs for ----
    def submit_invoice(self, doctype, doc, json_data=None):
        """POST /api/sales-invoices/{business_profile_id}"""
        if doctype == "Purchase Invoice":
            if doc.is_return:
                frappe.throw(
                    _(
                        "Marmin purchase debit note submission isn't implemented yet - "
                        "no confirmed docs page/example for it."
                    )
                )
            return self._submit_purchase_invoice(doc)
        if doctype != "Sales Invoice":
            frappe.throw(
                _("Marmin adapter only supports Sales Invoice and Purchase Invoice submission so far.")
            )
        if doc.is_return:
            return self._submit_credit_note(doc)

        settings = self.settings
        business_profile_id = settings.participant_id
        if not business_profile_id:
            frappe.throw(
                _(
                    "Business Profile ID (stored in Participant ID) is missing on "
                    "E-Invoice Provider Settings"
                )
            )

        base_url = self.get_base_url()
        url = f"{base_url}/api/sales-invoices/{business_profile_id}"
        headers = self.get_auth_headers({"Content-Type": "application/json"})

        payload = self._build_invoice_payload(doc)

        
        self.save_outgoing_payload(doc, payload)

        response = requests.post(url, headers=headers, json=payload, timeout=120)

        try:
            response_data = response.json()
        except Exception:
            response_data = response.text

        return response.status_code, response_data

    def _build_invoice_payload(self, doc):
        """Maps a Sales Invoice to Marmin's flat JSON shape"""
        default_vat_category = doc.custom_vat_category
        default_vat_rate = doc.taxes[0].rate if doc.taxes else 0
        default_exemption_label = doc.custom_vat_exemption_reason_code

        return {
            "profile_execution_id": MARMIN_PROFILE_EXECUTION_ID_STANDARD,
            "document_number": doc.name,
            "issue_date": str(doc.posting_date),
            "invoice_type_code": _marmin_sales_invoice_type_code(doc),
            "due_date": str(doc.due_date) if doc.due_date else str(doc.posting_date),
            "document_currency_code": doc.currency,
            "accounting_supplier_party": self._build_accounting_supplier_party(doc),
            "accounting_customer_party": self._build_accounting_customer_party(doc),
            "payment_means": self._build_payment_means(doc),
            "document_lines": [
                self._build_invoice_line(
                    item, default_vat_category, default_vat_rate, default_exemption_label
                )
                for item in doc.items
            ],
        }

    def _submit_credit_note(self, doc):
        """POST /api/sales-credit-notes/{business_profile_id"""
        settings = self.settings
        business_profile_id = settings.participant_id
        if not business_profile_id:
            frappe.throw(
                _(
                    "Business Profile ID (stored in Participant ID) is missing on "
                    "E-Invoice Provider Settings"
                )
            )

        base_url = self.get_base_url()
        url = f"{base_url}/api/sales-credit-notes/{business_profile_id}"
        headers = self.get_auth_headers({"Content-Type": "application/json"})

        payload = self._build_credit_note_payload(doc)

        self.save_outgoing_payload(doc, payload)

        response = requests.post(url, headers=headers, json=payload, timeout=120)

        try:
            response_data = response.json()
        except Exception:
            response_data = response.text

        return response.status_code, response_data

    def _build_credit_note_payload(self, doc):
        """Maps a return Sales Invoice to Marmin's credit note """
        default_vat_category = doc.custom_vat_category
        default_vat_rate = doc.taxes[0].rate if doc.taxes else 0
        default_exemption_label = doc.custom_vat_exemption_reason_code

        payload = {
            "profile_execution_id": MARMIN_PROFILE_EXECUTION_ID_STANDARD,
            "issue_date": str(doc.posting_date),
            "issue_time": _marmin_issue_time(doc),
            "credit_note_type_code": _marmin_sales_invoice_type_code(doc),
            "document_currency_code": doc.currency,
            "due_date": str(doc.due_date) if doc.due_date else str(doc.posting_date),
            "accounting_supplier_party": self._build_accounting_supplier_party(doc),
            "accounting_customer_party": self._build_accounting_customer_party(doc),
            "payment_means": self._build_payment_means(doc),
            "document_lines": [
                self._build_invoice_line(
                    item, default_vat_category, default_vat_rate, default_exemption_label
                )
                for item in doc.items
            ],
        }

       
        if not doc.return_against:
            frappe.throw(
                _(
                    "This credit note has no Return Against invoice set - Marmin "
                    "requires the original invoice's Document ID as document_number "
                    "for a credit note, and there's no Sales Invoice here to read it "
                    "from."
                )
            )
        original_invoice = frappe.get_doc("Sales Invoice", doc.return_against)
        if not original_invoice.custom_document_id:
            frappe.throw(
                _(
                    "Original invoice {0} has no Document ID (custom_document_id) yet - "
                    "it needs to have been successfully submitted to Marmin first, so "
                    "this credit note can reference its Marmin document id as "
                    "document_number."
                ).format(original_invoice.name)
            )
        payload["document_number"] = original_invoice.custom_document_id
        payload["billing_reference"] = [
            {
                "id": original_invoice.name,
                "issue_date": str(original_invoice.posting_date),
            }
        ]

        raw_reason = doc.custom_credit_note_reason_code
        if raw_reason:
            code, _sep, _reason = raw_reason.partition("-")
            payload["discrepancy_response"] = code.strip()

        return payload

    def _submit_purchase_invoice(self, doc):
        """POST /api/purchase-invoices/{business_profile_id}"""
        settings = self.settings
        business_profile_id = settings.participant_id
        if not business_profile_id:
            frappe.throw(
                _(
                    "Business Profile ID (stored in Participant ID) is missing on "
                    "E-Invoice Provider Settings"
                )
            )

        base_url = self.get_base_url()
        url = f"{base_url}/api/purchase-invoices/{business_profile_id}"
        headers = self.get_auth_headers({"Content-Type": "application/json"})

        payload = self._build_purchase_invoice_payload(doc)

        self.save_outgoing_payload(doc, payload)

        response = requests.post(url, headers=headers, json=payload, timeout=120)

        try:
            response_data = response.json()
        except Exception:
            response_data = response.text

        return response.status_code, response_data

    def _build_purchase_invoice_payload(self, doc):
        """Maps a Purchase Invoice to Marmin's flat JSON shape, per the real
        curl + full example JSON pasted from their purchase-invoices docs
        page. Reuses the same building blocks the Sales Invoice/credit note
        payloads already use """
        default_vat_category = doc.custom_vat_category
        default_vat_rate = doc.taxes[0].rate if doc.taxes else 0
        default_exemption_label = doc.custom_vat_exemption_reason_code

        supplier_doc = frappe.get_doc("Supplier", doc.supplier)
        company_doc = frappe.get_doc("Company", doc.company)

        payload = {
            "profile_execution_id": MARMIN_PROFILE_EXECUTION_ID_STANDARD,
            "document_number": doc.name,
            "issue_date": str(doc.posting_date),
            "issue_time": _marmin_issue_time(doc),
            "invoice_type_code": _marmin_purchase_invoice_type_code(doc),
            "due_date": str(doc.due_date) if doc.due_date else str(doc.posting_date),
            "document_currency_code": doc.currency,
            "accounting_supplier_party": self._build_purchase_supplier_party(doc),
           
            "accounting_customer_party": self._build_accounting_supplier_party(doc, as_customer=True),
            "payment_means": self._build_purchase_payment_means(doc),
            "document_lines": [
                self._build_invoice_line(
                    item, default_vat_category, default_vat_rate, default_exemption_label
                )
                for item in doc.items
            ],
        }
        if company_doc.tax_id:
            payload["buyer_customer_party"] = {"id": company_doc.tax_id}
        if supplier_doc.tax_id:
            payload["seller_supplier_party"] = {"id": supplier_doc.tax_id}

        return payload

    def _build_purchase_supplier_party(self, doc):
        """Seller party block for a Purchase Invoice """
        supplier_doc = frappe.get_doc("Supplier", doc.supplier)

        address_data = None
        if doc.supplier_address:
            address_data = frappe.get_doc("Address", doc.supplier_address)
        elif supplier_doc.supplier_primary_address:
            address_data = frappe.get_doc("Address", supplier_doc.supplier_primary_address)
        if not address_data:
            frappe.throw(_("Supplier address not found for {0}").format(doc.supplier))

        country_dict = country_code_mapping()
        country_code = "AE"
        if address_data.country and address_data.country.lower() in country_dict:
            country_code = country_dict[address_data.country.lower()]

        country_subentity = _marmin_uae_emirate_code(address_data.emirate)
        if country_code == "AE" and not country_subentity:
            frappe.throw(
                _(
                    "Supplier {0}'s address needs a recognised UAE emirate (Abu Dhabi, "
                    "Dubai, Sharjah, Ajman, Umm Al Quwain, Ras Al Khaimah or Fujairah) - "
                    "Marmin requires this for the supplier's postal address."
                ).format(doc.supplier)
            )

        endpoint_id = supplier_doc.custom_peppol_id
        if not endpoint_id:
            frappe.throw(
                _(
                    "Supplier {0} has no PEPPOL ID (Participant ID) set - Marmin "
                    "requires one on accounting_supplier_party.endpoint_id for every "
                    "purchase invoice. Set it on the Supplier the same way it's already "
                    "set for Customers."
                ).format(doc.supplier)
            )

        party = {
            "name": supplier_doc.supplier_name,
            "party_name": supplier_doc.supplier_name,
            "endpoint_id": endpoint_id,
            "endpoint_scheme_id": MARMIN_ENDPOINT_SCHEME_ID_UAE,
            "email": address_data.email_id,
            "telephone": address_data.phone,
            "postal_address": {
                "street_name": address_data.address_line1,
                "additional_street_name": address_data.address_line2,
                "city_name": address_data.city,
                "postal_zone": address_data.pincode,
                "country_subentity": country_subentity,
                "country": address_data.country or "United Arab Emirates",
                "country_code": country_code,
            },
        }

        if supplier_doc.tax_id:
            
            party["party_tax_scheme"] = {
                "company_id": supplier_doc.tax_id,
                "tax_scheme": "VAT",
            }

        
        registration_type = supplier_doc.custom_legal_registration_identifier_type
        if registration_type == "Commercial/Trade license":
            if not supplier_doc.custom_trade_license_number:
                frappe.throw(
                    _(
                        "Supplier {0}'s Legal Registration Identifier Type is "
                        "'Commercial/Trade license' but Trade License Number is "
                        "empty - Marmin requires both together."
                    ).format(doc.supplier)
                )
            if not supplier_doc.custom_legal_registration_authority:
                frappe.throw(
                    _(
                        "Supplier {0}'s Legal Registration Identifier Type is "
                        "'Commercial/Trade license' but Legal Registration Authority "
                        "(the issuing government body, e.g. 'Dubai Department of "
                        "Economy and Tourism') is empty - Marmin requires an "
                        "authority_name whenever a Trade License number is sent."
                    ).format(doc.supplier)
                )
            party["scheme_agency_id"] = "TL"
            party["company_id"] = supplier_doc.custom_trade_license_number
            party["authority_name"] = supplier_doc.custom_legal_registration_authority
        elif registration_type:
            
            pass

        # The supplier's own Marmin Business Profile ID - only if this
        # supplier is also on Marmin (Supplier > Marmin Profile ID).
        if supplier_doc.get("custom_marmin_profile_id"):
            party["profile_id"] = supplier_doc.custom_marmin_profile_id

        return party

    def _build_purchase_payment_means(self, doc):
        """Purchase Invoice has no Payments child table the way Sales
        Invoice does (that's a POS-only table) - purchase_json.py's own
        PEPPOL builder reads a single flat custom_payment_means_codes field
        straight off the Purchase Invoice doc instead, so this mirrors that
        same source rather than trying to reuse _build_payment_means's
        Payments-table walk, which doesn't apply here."""
        raw_value = (doc.get("custom_payment_means_codes") or "").strip()
        payment_code, _sep, _name = raw_value.partition(" - ")
        payment_code = payment_code.strip() or MARMIN_DEFAULT_PAYMENT_MEANS_CODE

        if payment_code not in MARMIN_APPROVED_PAYMENT_MEANS_CODES:
            frappe.throw(
                _(
                    "This invoice's payment means code '{0}' isn't one Marmin "
                    "accepts ({1}). Update Payment Means Code to a supported one."
                ).format(
                    payment_code,
                    ", ".join(sorted(MARMIN_APPROVED_PAYMENT_MEANS_CODES)),
                )
            )

        if payment_code in ("30", "54", "55", "49"):
            frappe.throw(
                _(
                    "This invoice's payment means code {0} needs additional details "
                    "(a supplier bank account, card, or mandate) this adapter doesn't "
                    "build for Purchase Invoice yet - use payment means code 1 "
                    "(Instrument not defined) or 10 (Cash) for now, or ask to have "
                    "this filled in."
                ).format(payment_code)
            )

        return [{"payment_means_code": payment_code}]

    def _build_payment_means(self, doc):
        """Build payment_means from this file's own"""
        entries = []

        for pm in _marmin_sales_payment_means(doc):
            payment_code = (pm.get("payment_means_code") or "").strip()
            if not payment_code:
                continue

            if payment_code not in MARMIN_APPROVED_PAYMENT_MEANS_CODES:
                frappe.throw(
                    _(
                        "This invoice's payment means code '{0}' isn't one Marmin "
                        "accepts ({1}). Update the Mode of Payment's Payment Means "
                        "Code to a supported one."
                    ).format(
                        payment_code,
                        ", ".join(sorted(MARMIN_APPROVED_PAYMENT_MEANS_CODES)),
                    )
                )

            entry = {"payment_means_code": payment_code}

            if payment_code == "30":
                payee_account = pm.get("payee_financial_account") or {}
                if not payee_account.get("id"):
                    frappe.throw(
                        _(
                            "This invoice's Mode of Payment needs a bank Account under "
                            "its Accounts table - Marmin requires payee_financial_account "
                            "for payment means code 30."
                        )
                    )
                entry["payee_financial_account"] = {
                    "id": payee_account.get("id"),
                    "name": payee_account.get("name"),
                }
            elif payment_code in ("54", "55", "49"):
                
                frappe.throw(
                    _(
                        "This invoice's Mode of Payment uses payment means code {0}, "
                        "which needs card_account or payment_mandate details this "
                        "adapter doesn't build yet - use a bank transfer (30) or cash "
                        "(10) Mode of Payment instead, or ask to have this one filled "
                        "in."
                    ).format(payment_code)
                )

            entries.append(entry)

        if not entries:
            entries = [{"payment_means_code": MARMIN_DEFAULT_PAYMENT_MEANS_CODE}]

        return entries

    def _build_accounting_supplier_party(self, doc, as_customer=False):
        """Seller party block, built from the Company doctype """
        from frappe.contacts.doctype.address.address import get_default_address

        company_doc = frappe.get_doc("Company", doc.company)

        endpoint_id = self.settings.participant_id
        if not endpoint_id:
            frappe.throw(
                _(
                    "Participant ID (Business Profile ID) is missing on "
                    "E-Invoice Provider Settings - Marmin requires it as "
                    "this invoice's accounting_supplier_party.endpoint_id."
                )
            )

        address_name = get_default_address("Company", company_doc.name)
        if not address_name:
            frappe.throw(
                _(
                    "Company {0} has no Address linked to it - Marmin "
                    "requires a postal_address on accounting_supplier_party. "
                    "Add one under Company > Address and Contacts."
                ).format(company_doc.name)
            )
        address_data = frappe.get_doc("Address", address_name)

        country_dict = country_code_mapping()
        country_code = "AE"
        if address_data.country and address_data.country.lower() in country_dict:
            country_code = country_dict[address_data.country.lower()]

        country_subentity = _marmin_uae_emirate_code(address_data.emirate)
        if country_code == "AE" and not country_subentity:
            frappe.throw(
                _(
                    "Company {0}'s address needs a recognised UAE emirate "
                    "(Abu Dhabi, Dubai, Sharjah, Ajman, Umm Al Quwain, Ras Al "
                    "Khaimah or Fujairah) - Marmin requires this for the "
                    "supplier's postal address."
                ).format(company_doc.name)
            )

      
        if country_code == "AE" and not address_data.phone and not as_customer:
            frappe.throw(
                _(
                    "Company {0}'s Address has no Phone set - Marmin "
                    "requires a telephone number on accounting_supplier_party "
                    "for UAE suppliers."
                ).format(company_doc.name)
            )

        party = {
            "name": company_doc.company_name,
            "party_name": company_doc.company_name,
            "endpoint_id": endpoint_id,
            "endpoint_scheme_id": MARMIN_ENDPOINT_SCHEME_ID_UAE,
            "email": address_data.email_id,
            "postal_address": {
                "street_name": address_data.address_line1,
                "additional_street_name": address_data.address_line2,
                "city_name": address_data.city,
                "postal_zone": address_data.pincode,
                "country_subentity": country_subentity,
                "country": address_data.country or "United Arab Emirates",
                "country_code": country_code,
            },
        }

        if not as_customer:
            party["telephone"] = address_data.phone

        # Our own Marmin Business Profile ID - on the supplier block for Sales
        # Invoices and on the customer block for Purchase Invoices.
        party["profile_id"] = self.settings.participant_id

        
        if company_doc.tax_id:
            party["party_tax_scheme"] = {
                "company_id": company_doc.tax_id,
                "tax_scheme": "VAT",
            }

        return party

    def _build_accounting_customer_party(self, doc):
        """Buyer party block, built from the same Customer + Address fields
        Flick's own PEPPOL builder already reads (build_uae_invoice_json in
        json_einvoice.py) """
        customer_doc = frappe.get_doc("Customer", doc.customer)

        address_data = None
        if doc.customer_address:
            address_data = frappe.get_doc("Address", doc.customer_address)
        elif customer_doc.customer_primary_address:
            address_data = frappe.get_doc("Address", customer_doc.customer_primary_address)
        if not address_data:
            frappe.throw(_("Customer address not found for {0}").format(doc.customer))

        country_dict = country_code_mapping()
        country_code = "AE"
        if address_data.country and address_data.country.lower() in country_dict:
            country_code = country_dict[address_data.country.lower()]

        country_subentity = _marmin_uae_emirate_code(address_data.emirate)
        if country_code == "AE" and not country_subentity:
            frappe.throw(
                _(
                    "Customer {0}'s address needs a recognised UAE emirate (Abu Dhabi, "
                    "Dubai, Sharjah, Ajman, Umm Al Quwain, Ras Al Khaimah or Fujairah) - "
                    "Marmin requires this for the buyer's postal address."
                ).format(doc.customer)
            )

        endpoint_id = customer_doc.custom_peppol_id
        if not endpoint_id:
            frappe.throw(
                _(
                    "Customer {0} has no PEPPOL ID (Participant ID) set - Marmin "
                    "requires one on accounting_customer_party.endpoint_id for every "
                    "invoice. Set it on the Customer the same way it's already set "
                    "for Flick."
                ).format(doc.customer)
            )

        party = {
            "name": customer_doc.customer_name,
            "party_name": customer_doc.customer_name,
            "endpoint_id": endpoint_id,
            "endpoint_scheme_id": MARMIN_ENDPOINT_SCHEME_ID_UAE,
            "email": address_data.email_id,
            "postal_address": {
                "street_name": address_data.address_line1,
                "additional_street_name": address_data.address_line2,
                "city_name": address_data.city,
                "postal_zone": address_data.pincode,
                "country_subentity": country_subentity,
                "country": address_data.country or "United Arab Emirates",
                "country_code": country_code,
            },
        }

       
        if customer_doc.tax_id:
            party["party_tax_scheme"] = {
                "company_id": customer_doc.tax_id,
                "tax_scheme": "VAT",
            }

        return party

    def _build_invoice_line(
        self, item, default_vat_category, default_vat_rate, default_exemption_label
    ):
        """One document_lines entry. classified_tax_category reuses the same
        custom_vat_category labels (and per-item Item Tax Template override)
        that the Flick/PEPPOL builder in json_einvoice.py already uses via
        _marmin_vat_category_code() """
        vat_category = default_vat_category
        tax_rate = default_vat_rate
        exemption_label = default_exemption_label

        if item.item_tax_template:
            item_tax_template = frappe.get_doc("Item Tax Template", item.item_tax_template)
            vat_category = item_tax_template.custom_vat_category or default_vat_category
            exemption_label = (
                item_tax_template.custom_vat_exemption_reason_code or default_exemption_label
            )
            if item_tax_template.taxes:
                tax_rate = item_tax_template.taxes[0].tax_rate

        vat_code = _marmin_vat_category_code(vat_category) if vat_category else "S"

        classified_tax_category = {
            "id": vat_code,
            "percent": float(tax_rate or 0),
            "tax_scheme": "VAT",
        }

        if vat_code == "E":
            
            if not exemption_label:
                frappe.throw(
                    _(
                        "Item {0} is VAT-exempt but has no VAT Exemption Reason Code set "
                        "(on its Item Tax Template or on this Sales Invoice) - Marmin "
                        "requires one for exempt lines."
                    ).format(item.item_code)
                )
            code, _sep, description = exemption_label.partition(" - ")
            classified_tax_category["tax_exemption_reason_code"] = code.strip()
            classified_tax_category["tax_exemption_reason"] = (description or exemption_label).strip()

        return {
            "name": item.item_name,
            "description": item.description or item.item_name,
            "quantity": item.qty,
            "unit_code": self._unit_code(item.uom),
            "price": {
                "base_amount": item.rate,
                "base_quantity": 1,
            },
            "classified_tax_category": classified_tax_category,
        }

    def _unit_code(self, uom):
        if not uom:
            return "EA"
        return MARMIN_UOM_TO_UNECE_CODE.get(uom.strip().lower(), "EA")


MARMIN_PROVIDER_NAME = "Marmin AI Software Design LLC"


@frappe.whitelist()
def is_marmin_active():
    """True if any Company uses Marmin as its Accredited Service Provider.
    Used by public/js/marmin_party.js to show the Marmin Profile ID field
    on Supplier only when Marmin is actually in use."""
    return bool(
        frappe.db.exists(
            "Company", {"custom_accredited_service_providers": MARMIN_PROVIDER_NAME}
        )
    )


MARMIN_WEBHOOK_SIGNATURE_HEADER = "x-marmin-signature"


def _verify_marmin_webhook_signature(raw_body, received_signature, webhook_secret):
    """HMAC-SHA256(key=webhook_secret, message=raw_body), base64-encoded -
    this is exactly Marmin's own verifyWebhookSignature function from
    their Webhook Signature Verification docs page, translated from the
    JS sample given there."""
    if not received_signature or not webhook_secret:
        return False

    body_bytes = raw_body if isinstance(raw_body, bytes) else raw_body.encode("utf-8")
    expected_signature = base64.b64encode(
        hmac.new(webhook_secret.encode("utf-8"), body_bytes, hashlib.sha256).digest()
    ).decode("utf-8")

    return hmac.compare_digest(expected_signature, received_signature)


@frappe.whitelist(allow_guest=True)  # nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method
def marmin_webhook_listener():
    """Listener for Marmin's webhook events - the URL
    get_webhook_listener_url() above hands you to paste into the Marmin
    Web Application's Developer Dashboard > Webhooks config screen."""
    raw_body = frappe.request.get_data()  # raw bytes - see the signature note above

    try:
        payload = json.loads(raw_body)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Marmin Webhook Invalid JSON")
        frappe.local.response["http_status_code"] = 400
        return {"received": False, "error": "invalid JSON"}

    profile_id = payload.get("profile_id")
    resource_id = payload.get("resource_id")
    event_type = payload.get("event_type")
    webhook_event_id = payload.get("webhook_event_id")

    settings_name = frappe.db.get_value(
        "E-Invoice Provider Settings",
        {"provider": "Marmin AI Software Design LLC", "participant_id": profile_id},
        "name",
    )
    if not settings_name:
        frappe.log_error(
            f"No E-Invoice Provider Settings row found for Marmin profile_id "
            f"{profile_id} (webhook_event_id {webhook_event_id})",
            "Marmin Webhook Unknown Profile",
        )
        frappe.local.response["http_status_code"] = 404
        return {"received": False, "error": "unknown profile_id"}

    settings = frappe.get_doc("E-Invoice Provider Settings", settings_name)
    webhook_secret = settings.get_password("webhook_secret")
    received_signature = frappe.request.headers.get(MARMIN_WEBHOOK_SIGNATURE_HEADER)

    if not _verify_marmin_webhook_signature(raw_body, received_signature, webhook_secret):
        
        frappe.log_error(
            f"Signature check failed for Marmin webhook_event_id "
            f"{webhook_event_id} (profile_id {profile_id}) - header "
            f"checked: {MARMIN_WEBHOOK_SIGNATURE_HEADER}",
            "Marmin Webhook Signature Mismatch",
        )
        frappe.local.response["http_status_code"] = 401
        return {"received": False, "error": "signature verification failed"}

    
    sales_invoice_row = frappe.db.get_value(
        "Sales Invoice", {"custom_document_id": resource_id}, ["name", "is_return"], as_dict=True
    )
    purchase_invoice_name = frappe.db.get_value(
        "Purchase Invoice", {"custom_document_id": resource_id}, "name"
    )

    if purchase_invoice_name:
        resource_path = "purchase-invoices"
    elif sales_invoice_row and sales_invoice_row.is_return:
        resource_path = "sales-credit-notes"
    else:
        resource_path = "sales-invoices"
    adapter = MarminAdapter(settings)
    reporting_status = None
    try:
        base_url = adapter.get_base_url()
        url = f"{base_url}/api/{resource_path}/{resource_id}/peppol-status-logs"
        response = requests.get(url, headers=adapter.get_auth_headers())
        try:
            status_log_body = response.json()
        except Exception:
            status_log_body = response.text
        if isinstance(status_log_body, list):
            reporting_status = MarminAdapter._reporting_status_from_status_logs(
                status_log_body
            )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Marmin Webhook Status Refetch Error")

    frappe.get_doc(
        {
            "doctype": "UAE E-Invoice Webhook Logs",
            "webhook_response": raw_body.decode("utf-8", errors="replace"),
            "document_id": resource_id,
            "participant_id": profile_id,
            "event_type": event_type,
            "reporting_status": reporting_status,
        }
    ).insert(ignore_permissions=True)

    if resource_id and reporting_status:
        if sales_invoice_row:
            frappe.db.set_value(
                "Sales Invoice",
                sales_invoice_row.name,
                "custom_reporting_status",
                reporting_status,
            )

        if purchase_invoice_name:
            frappe.db.set_value(
                "Purchase Invoice",
                purchase_invoice_name,
                "custom_reporting_status",
                reporting_status,
            )

    frappe.db.commit()  # nosemgrep: frappe-manual-commit

    return {"received": True, "processed": True}