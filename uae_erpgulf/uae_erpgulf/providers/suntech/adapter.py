"""Suntech Business Solutions DMCC adapter (Tax Compliance Agent platform)."""

import json
from decimal import Decimal, ROUND_HALF_UP
import frappe
import requests
from frappe import _
from frappe.utils import now_datetime, strip_html
from uae_erpgulf.uae_erpgulf.country_code import country_code_mapping
from uae_erpgulf.uae_erpgulf.providers.base import BaseAdapter

SUNTECH_PROVIDER_NAME = "Suntech Business Solutions DMCC"
SUNTECH_ENDPOINT_SCHEME = "0235"
SUNTECH_TIMEOUT = 60

PROCESS_BILLING = {
    "profile_id": "urn:peppol:bis:billing",
    "customization_id": "urn:peppol:pint:billing-1@ae-1",
}
PROCESS_SELF_BILLING = {
    "profile_id": "urn:peppol:bis:selfbilling",
    "customization_id": "urn:peppol:pint:selfbilling-1@ae-1",
}

DISCREPANCY_CODES = {"DL8.61.1.A", "DL8.61.1.B", "DL8.61.1.C", "DL8.61.1.D", "DL8.61.1.E", "VD"}

UOM_TO_UNECE = {
    "nos": "EA", "unit": "EA", "each": "EA", "pcs": "EA", "piece": "EA",
    "kg": "KGM", "kilogram": "KGM", "gram": "GRM", "gm": "GRM",
    "litre": "LTR", "liter": "LTR", "ltr": "LTR",
    "meter": "MTR", "metre": "MTR", "mtr": "MTR",
    "box": "BX", "pair": "PR", "dozen": "DZN", "hour": "HUR", "day": "DAY",
}

# invoice status (§14.1) -> our custom_reporting_status
STATUS_TO_REPORTING = {1: "pending", 2: "reported", 3: "rejected", 4: "failed"}


# ---------------------------------------------------------------- helpers
def _money(value):
    return str(Decimal(str(value or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP))


def _qty(value):
    return str(Decimal(str(value or 0)).quantize(Decimal("0.000001"), ROUND_HALF_UP))


def _emirate_code(emirate_name):
    if not emirate_name:
        return None
    return {
        "abu dhabi": "AUH", "dubai": "DXB", "sharjah": "SHJ", "ajman": "AJM",
        "umm al quwain": "UAQ", "ras al khaimah": "RAK", "fujairah": "FUJ",
    }.get(emirate_name.strip().lower())


def _vat_category_code(label):
    if not label:
        return None
    code = {
        "s - standard rated": "S", "standard rated": "S", "s": "S",
        "z - zero rated": "Z", "zero rated": "Z", "z": "Z",
        "e - exempt from tax": "E", "exempt from tax": "E", "e": "E",
        "ae - vat reverse charge": "AE", "vat reverse charge": "AE",
        "reverse charge": "AE", "ae": "AE",
        "o - not subject to vat": "O", "not subject to vat": "O", "o": "O",
        "n - margin scheme": "N", "margin scheme": "N", "n": "N",
    }.get(label.strip().lower())
    if not code:
        frappe.throw(_("Invalid VAT Category: {0}. Must be one of S, Z, E, AE, O, N.").format(label))
    return code


def _transaction_type_code(doc):
    """custom_invoice_transaction_type_code (e.g. 'XXXXXXX1 : Export') ->
    the 8-character 0/1 string BTAE-02 needs (§14.9)."""
    raw = (doc.get("custom_invoice_transaction_type_code") or "").split(":")[0].strip()
    bits = "".join("1" if c == "1" else "0" for c in raw)
    return (bits + "00000000")[:8]


def _address_block(address_data, country_dict):
    country_code = "AE"
    if address_data.country and address_data.country.lower() in country_dict:
        country_code = country_dict[address_data.country.lower()]
    subdivision = _emirate_code(address_data.get("emirate"))
    if not subdivision:
        if country_code == "AE":
            frappe.throw(
                _("Address {0} needs a recognised UAE emirate (Abu Dhabi, Dubai, Sharjah, "
                  "Ajman, Umm Al Quwain, Ras Al Khaimah or Fujairah).").format(address_data.name)
            )
        subdivision = address_data.state or address_data.city
    return {
        "address_line_1": address_data.address_line1,
        "address_line_2": address_data.address_line2 or None,
        "city": address_data.city,
        "post_code": address_data.pincode or None,
        "country_subdivision": subdivision,
        "country_code": country_code,
        "contact_telephone_number": address_data.phone or None,
        "contact_email_address": address_data.email_id or None,
    }


class SuntechAdapter(BaseAdapter):
    # XML is generated asynchronously and the PDF only once the invoice is
    # Completed, so don't try to fetch them straight after submit - use the
    # Get Document buttons (or the webhook) once the invoice has moved on.
    AUTO_FETCH_DOCUMENTS_ON_SUBMIT = False

    # ---------------------------------------------------------------- auth
    def get_api_url(self):
        """Base URL may be entered with or without /api/v1."""
        base = (self.get_base_url() or "").rstrip("/")
        if not base:
            frappe.throw(_("Please enter Base URL on E-Invoice Provider Settings."))
        if not base.endswith("/api/v1"):
            base = f"{base}/api/v1"
        return base

    def _fetch_token(self):
        settings = self.settings
        client_id = settings.client_id
        client_secret = settings.get_password("client_secret")
        if not client_id or not client_secret:
            frappe.throw(_("Please enter Client ID and Client Secret on E-Invoice Provider Settings."))

        response = requests.post(
            f"{self.get_api_url()}/oauth/token/",
            data={"client_id": client_id, "client_secret": client_secret},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=SUNTECH_TIMEOUT,
        )
        if not response.ok:
            frappe.throw(
                _("Suntech token request failed ({0}): {1}").format(response.status_code, response.text)
            )

        data = response.json()
        access_token = data.get("access_token")
        if not access_token:
            frappe.throw(_("Access token not found in Suntech token response: {0}").format(data))

        # 600 s token - cache it with a 30 s safety margin (§3.5)
        expires_in = data.get("expires_in")
        if isinstance(expires_in, (int, float)) and expires_in > 60:
            self.set_cached_token(access_token, expires_in_sec=int(expires_in) - 30)
        else:
            self.set_cached_token(access_token, expires_in_sec=540)
        return access_token

    def get_auth_headers(self, extra=None):
        headers = dict(extra or {})
        headers["Authorization"] = f"Bearer {self.get_valid_token()}"
        return headers

    def _request(self, method, path, **kwargs):
        """Authenticated call; on a 401 get a fresh token once and retry (§3.5)."""
        url = f"{self.get_api_url()}{path}"
        extra = kwargs.pop("headers", None)
        response = requests.request(
            method, url, headers=self.get_auth_headers(extra), timeout=SUNTECH_TIMEOUT, **kwargs
        )
        if response.status_code == 401:
            self._fetch_token()
            response = requests.request(
                method, url, headers=self.get_auth_headers(extra), timeout=SUNTECH_TIMEOUT, **kwargs
            )
        return response

    def verify_auth(self):
        settings = self.settings
        try:
            self._fetch_token()
            settings.db_set("last_test_status", "Passed")
            settings.db_set("last_test_on", now_datetime())
            return {"status": "success", "response": "Token issued successfully"}
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Suntech Verify Error")
            settings.db_set("last_test_status", "Failed")
            settings.db_set("last_test_on", now_datetime())
            return {"status": "error", "message": str(e)}

    def get_participant_details(self):
        """The API has no organisation endpoint - the token response carries
        the organisation the API client is bound to (§3.2)."""
        settings = self.settings
        response = requests.post(
            f"{self.get_api_url()}/oauth/token/",
            data={"client_id": settings.client_id, "client_secret": settings.get_password("client_secret")},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=SUNTECH_TIMEOUT,
        )
        if not response.ok:
            frappe.throw(_("Suntech API Error: {0}").format(response.text))
        data = response.json()
        return {
            "status": "success",
            "response": {"organization": data.get("organization"), "client_name": data.get("client_name")},
        }

    def lookup_peppol_id(self, peppol_id):
        frappe.throw(_("Suntech's API has no Peppol lookup endpoint."))

    def update_participant(self, company_doc):
        frappe.throw(_("Suntech organisation details are managed in the Suntech portal, not via the API."))

    # ------------------------------------------------------------- submit
    def submit_invoice(self, doctype, doc, json_data=None):
        if doctype not in ("Sales Invoice", "Purchase Invoice"):
            frappe.throw(_("Suntech adapter supports Sales Invoice and Purchase Invoice only."))

        payload = self._build_payload(doctype, doc)
        self.save_outgoing_payload(doc, payload)

        response = self._request(
            "POST", "/invoices/", json=payload, headers={"Content-Type": "application/json"}
        )
        try:
            response_data = response.json()
        except Exception:
            response_data = response.text
        return response.status_code, response_data

    def _invoice_type_code(self, doctype, doc):
        if doctype == "Purchase Invoice":
            return "261" if doc.is_return else "389"
        out_of_scope = (doc.get("custom_vat_category") or "").strip().lower().startswith("o")
        if doc.is_return:
            return "81" if out_of_scope else "381"
        return "480" if out_of_scope else "380"

    def _build_payload(self, doctype, doc):
        type_code = self._invoice_type_code(doctype, doc)
        is_credit = type_code in ("381", "81", "261")
        country_dict = country_code_mapping()

        if doctype == "Purchase Invoice":
            seller = self._party_from_supplier(doc, country_dict)
            buyer = self._party_from_company(doc, country_dict)
            process_control = PROCESS_SELF_BILLING
        else:
            seller = self._party_from_company(doc, country_dict)
            buyer = self._party_from_customer(doc, country_dict)
            process_control = PROCESS_BILLING

        lines, vat_breakdowns, line_total, vat_total = self._build_lines(doc)
        total_with_vat = line_total + vat_total

        conversion_rate = Decimal(str(doc.conversion_rate or 1))
        is_aed = (doc.currency or "AED").upper() == "AED"

        detail = {
            "transaction_type_code": _transaction_type_code(doc),
            "invoice_currency_code": (doc.currency or "AED").upper(),
            "issue_time": self._issue_time(doc),
            "process_control": dict(process_control),
            "seller": seller,
            "buyer": buyer,
            "totals": {
                "sum_of_invoice_line_net_amount": _money(line_total),
                "sum_of_allowances_on_document_level": "0.00",
                "sum_of_charges_on_document_level": "0.00",
                "invoice_total_amount_without_vat": _money(line_total),
                "invoice_total_vat_amount": _money(vat_total),
                "invoice_total_amount_with_vat": _money(total_with_vat),
                "paid_amount": "0.00",
                "rounding_amount": "0.00",
                "amount_due_for_payment": _money(total_with_vat),
                "invoice_total_amount_with_vat_in_aed": _money(
                    total_with_vat if is_aed else total_with_vat * conversion_rate
                ),
                "tax_included_indicator": False,
            },
            "vat_breakdowns": vat_breakdowns,
            "lines": lines,
        }

        if not is_aed:
            detail["tax_currency_code"] = "AED"
            detail["currency_exchange_rate"] = str(
                conversion_rate.quantize(Decimal("0.000001"), ROUND_HALF_UP)
            )

        if doc.get("custom_invoice_note"):
            detail["invoice_note"] = doc.custom_invoice_note

        payment_instructions = self._payment_instructions(doc)
        if payment_instructions:
            detail["payment_instructions"] = payment_instructions

        if is_credit:
            detail.update(self._credit_note_fields(doctype, doc))
        elif doc.due_date:
            detail["payment_due_date"] = str(doc.due_date)

        return {
            "name": doc.name,
            "invoice_number": doc.name,
            "issue_date": str(doc.posting_date),
            "invoice_type_code": type_code,
            "detail": detail,
        }

    def _issue_time(self, doc):
        t = doc.posting_time
        if not t:
            return None
        if hasattr(t, "total_seconds"):
            s = int(t.total_seconds())
            return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"
        return frappe.utils.get_time(t).strftime("%H:%M:%S")

    def _credit_note_fields(self, doctype, doc):
        raw = (doc.get("custom_credit_note_reason_code") or "").strip()
        if not raw:
            frappe.throw(_("Please select a Credit Note Reason Code before submitting this return."))
        # "DL8.61.1.A-Cancellation" -> "DL8.61.1.A"
        code = raw.split("-", 1)[0].strip()
        if code not in DISCREPANCY_CODES:
            frappe.throw(
                _("Credit Note Reason Code {0} isn't one Suntech accepts ({1}).").format(
                    code, ", ".join(sorted(DISCREPANCY_CODES))
                )
            )

        fields = {"discrepancy_response_code": code}

        # VD credit notes carry no preceding reference (§10, §11.1)
        if code != "VD":
            if not doc.return_against:
                frappe.throw(_("This return has no Return Against invoice set."))
            original = frappe.get_doc(doctype, doc.return_against)
            fields["preceding_invoice_references"] = [
                {
                    "preceding_invoice_reference": original.name,
                    "preceding_invoice_issue_date": str(original.posting_date),
                }
            ]
        return fields

    # ------------------------------------------------------------- parties
    def _party_from_company(self, doc, country_dict):
        from frappe.contacts.doctype.address.address import get_default_address

        company = frappe.get_doc("Company", doc.company)
        endpoint = self.settings.participant_id
        if not endpoint:
            frappe.throw(_("Participant ID (your Peppol ID / TIN) is missing on E-Invoice Provider Settings."))

        address_name = get_default_address("Company", company.name)
        if not address_name:
            frappe.throw(_("Company {0} has no Address linked to it.").format(company.name))
        address = frappe.get_doc("Address", address_name)

        party = {
            "name": company.company_name,
            "vat_identifier": company.tax_id or None,
            "tax_scheme": "VAT",
            "electronic_address": endpoint,
            "electronic_address_scheme": SUNTECH_ENDPOINT_SCHEME,
        }
        party.update(_address_block(address, country_dict))
        return party

    def _party_from_customer(self, doc, country_dict):
        customer = frappe.get_doc("Customer", doc.customer)
        address = None
        if doc.customer_address:
            address = frappe.get_doc("Address", doc.customer_address)
        elif customer.customer_primary_address:
            address = frappe.get_doc("Address", customer.customer_primary_address)
        if not address:
            frappe.throw(_("Customer address not found for {0}").format(doc.customer))
        if not customer.get("custom_peppol_id"):
            frappe.throw(_("Customer {0} has no Peppol ID set.").format(doc.customer))

        party = {
            "name": customer.customer_name,
            "vat_identifier": customer.tax_id or None,
            "tax_scheme": "VAT",
            "electronic_address": customer.custom_peppol_id,
            "electronic_address_scheme": SUNTECH_ENDPOINT_SCHEME,
        }
        party.update(_address_block(address, country_dict))
        self._add_legal_registration(party, customer)
        if customer.get("custom_fz_beneficiary_id"):
            party["beneficiary_identifier"] = customer.custom_fz_beneficiary_id
        return party

    def _party_from_supplier(self, doc, country_dict):
        supplier = frappe.get_doc("Supplier", doc.supplier)
        address = None
        if doc.supplier_address:
            address = frappe.get_doc("Address", doc.supplier_address)
        elif supplier.supplier_primary_address:
            address = frappe.get_doc("Address", supplier.supplier_primary_address)
        if not address:
            frappe.throw(_("Supplier address not found for {0}").format(doc.supplier))
        if not supplier.get("custom_peppol_id"):
            frappe.throw(_("Supplier {0} has no Peppol ID set.").format(doc.supplier))

        party = {
            "name": supplier.supplier_name,
            "vat_identifier": supplier.tax_id or None,
            "tax_scheme": "VAT",
            "electronic_address": supplier.custom_peppol_id,
            "electronic_address_scheme": SUNTECH_ENDPOINT_SCHEME,
        }
        party.update(_address_block(address, country_dict))
        self._add_legal_registration(party, supplier)
        return party

    def _add_legal_registration(self, party, party_doc):
        if party_doc.get("custom_legal_registration_identifier_type") != "Commercial/Trade license":
            return
        if not party_doc.get("custom_trade_license_number"):
            frappe.throw(
                _("{0} is set to 'Commercial/Trade license' but Trade License Number is empty.").format(
                    party_doc.name
                )
            )
        party["legal_registration_identifier"] = party_doc.custom_trade_license_number
        party["legal_registration_identifier_type"] = "TL"
        if party_doc.get("custom_legal_registration_authority"):
            party["authority_name"] = party_doc.custom_legal_registration_authority

    # --------------------------------------------------------------- lines
    def _build_lines(self, doc):
        default_category = doc.get("custom_vat_category")
        default_rate = doc.taxes[0].rate if doc.taxes else 0
        default_exemption = doc.get("custom_vat_exemption_reason_code")
        conversion_rate = Decimal(str(doc.conversion_rate or 1))

        lines = []
        breakdown = {}
        line_total = Decimal("0")

        for idx, item in enumerate(doc.items, 1):
            category, rate, exemption = default_category, default_rate, default_exemption
            if item.item_tax_template:
                template = frappe.get_doc("Item Tax Template", item.item_tax_template)
                category = template.get("custom_vat_category") or category
                exemption = template.get("custom_vat_exemption_reason_code") or exemption
                if template.taxes:
                    rate = template.taxes[0].tax_rate

            vat_code = _vat_category_code(category) if category else "S"
            rate = Decimal(str(rate or 0))
            qty = abs(Decimal(str(item.qty or 0)))
            net_amount = abs(Decimal(str(item.net_amount or item.amount or 0))).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
            price = (net_amount / qty) if qty else Decimal("0")
            line_vat = (net_amount * rate / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
            line_total += net_amount

            vat_info = {"vat_category_code": vat_code, "vat_rate": _money(rate), "tax_scheme": "VAT"}
            if vat_code == "E":
                if not exemption:
                    frappe.throw(_("Item {0} is VAT-exempt but has no VAT Exemption Reason Code.").format(item.item_code))
                ex_code, _sep, ex_text = exemption.partition(" - ")
                vat_info["vat_exemption_reason_code"] = ex_code.strip()
                vat_info["vat_exemption_reason_text"] = (ex_text or exemption).strip()

            description = strip_html(item.description or "").strip() or item.item_name

            line = {
                "line_id": str(idx),
                "invoiced_quantity": _qty(qty),
                "invoiced_quantity_unit_of_measure_code": UOM_TO_UNECE.get((item.uom or "").strip().lower(), "EA"),
                "line_net_amount": _money(net_amount),
                "item_net_price": _qty(price),
                "item_price_base_quantity": "1.000000",
                "item_name": item.item_name,
                "item_description": description,
                "line_amount_in_aed": _money(net_amount * conversion_rate),
                "vat_line_amount_in_aed": _money(line_vat * conversion_rate),
                "vat_info": [vat_info],
            }

            item_type = (item.get("custom_item_type_codes") or "").strip()[:1].upper()
            if item_type in ("G", "S", "B"):
                line["item_type"] = item_type
            if item.get("custom_hs_code_"):
                line["classifications"] = [
                    {"classification_identifier": item.custom_hs_code_, "classification_identifier_scheme": "HS"}
                ]
            if item.get("custom_sac_code"):
                line["service_accounting_codes"] = [
                    {"code": item.custom_sac_code, "scheme_identifier": "SAC"}
                ]

            lines.append(line)

            key = (vat_code, rate)
            breakdown.setdefault(key, {"taxable": Decimal("0"), "exemption": vat_info})
            breakdown[key]["taxable"] += net_amount

        vat_breakdowns = []
        vat_total = Decimal("0")
        for (vat_code, rate), row in breakdown.items():
            tax = (row["taxable"] * rate / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
            vat_total += tax
            entry = {
                "taxable_amount": _money(row["taxable"]),
                "tax_amount": _money(tax),
                "vat_category_code": vat_code,
                "tax_scheme_code": "VAT",
                "vat_category_rate": _money(rate),
            }
            if vat_code == "E":
                entry["vat_exemption_reason_code"] = row["exemption"].get("vat_exemption_reason_code")
                entry["vat_exemption_reason_text"] = row["exemption"].get("vat_exemption_reason_text")
            vat_breakdowns.append(entry)

        return lines, vat_breakdowns, line_total, vat_total

    def _payment_instructions(self, doc):
        raw = (doc.get("custom_payment_means_codes") or "").strip()
        if not raw:
            return None
        code, _sep, text = raw.partition(" - ")
        entry = {"payment_means_type_code": code.strip()}
        if text:
            entry["payment_means_text"] = text.strip()
        if code.strip() in ("30", "58") and doc.get("company_bank_account"):
            bank = frappe.get_doc("Bank Account", doc.company_bank_account)
            entry["payment_account_identifier"] = bank.iban or bank.bank_account_no
            entry["payment_account_identifier_scheme"] = "IBAN"
            entry["payment_account_name"] = bank.account_name
        return [entry]

    # ------------------------------------------------------ status / docs
    def _document_id(self, doc):
        if not doc.custom_submit_response:
            frappe.throw(_("Submit response not found in Invoice"))
        try:
            response_data = json.loads(doc.custom_submit_response)
        except Exception:
            response_data = {}
        document_id = (response_data.get("id") if isinstance(response_data, dict) else None) or doc.get(
            "custom_document_id"
        )
        if not document_id:
            frappe.throw(_("Suntech invoice id not found in submit response"))
        return document_id

    def _get_invoice(self, document_id):
        return self._request("GET", f"/invoices/{document_id}/")

    def get_document_status(self, doctype, doc):
        response = self._get_invoice(self._document_id(doc))
        try:
            body = response.json()
        except Exception:
            body = response.text

        result = {"http_status": response.status_code, "response": body}
        reporting_status = self.get_status_from_document_status(body)
        if reporting_status:
            result["reporting_status"] = reporting_status
        return result

    def get_status_from_document_status(self, body):
        if not isinstance(body, dict):
            return None
        if body.get("c5_mls_status") == 4:
            return "reported"
        return STATUS_TO_REPORTING.get(body.get("status"))

    def _download(self, doc, path_field, label):
        response = self._get_invoice(self._document_id(doc))
        if response.status_code != 200:
            frappe.throw(_("Suntech API Error: {0}").format(response.text))
        s3_uri = response.json().get(path_field)
        if not s3_uri:
            frappe.throw(_("Suntech hasn't generated the {0} for this invoice yet - try again later.").format(label))

        link = self._request(
            "POST", "/documents/download/", json={"s3_uri": s3_uri}, headers={"Content-Type": "application/json"}
        )
        if link.status_code not in (200, 201):
            frappe.throw(_("Suntech API Error: {0}").format(link.text))

        file_response = requests.get(link.json().get("download_url"), timeout=SUNTECH_TIMEOUT)
        if file_response.status_code != 200:
            frappe.throw(_("Could not download the {0} from Suntech.").format(label))
        return file_response

    def get_document_xml(self, doctype, doc):
        return self._download(doc, "invoice_xml_location_path", "XML").text

    def get_document_pdf(self, doctype, doc):
        return self._download(doc, "pdf_location_path", "PDF").content

    # ------------------------------------------------------------ webhooks
    _WEBHOOK_PORTAL_MESSAGE = _(
        "Suntech webhooks are configured in the Suntech portal (Settings > Webhooks), not through "
        "the API. Use this row's Webhook URL as the endpoint there, choose HS256 JWT auth, and put "
        "the same shared secret in this row's Webhook Secret field."
    )

    def register_webhook(self):
        frappe.throw(self._WEBHOOK_PORTAL_MESSAGE)

    def get_subscription(self):
        frappe.throw(self._WEBHOOK_PORTAL_MESSAGE)

    def get_webhook_deliveries(self):
        frappe.throw(self._WEBHOOK_PORTAL_MESSAGE)

    def get_webhook_listener_url(self):
        return frappe.utils.get_url(
            "/api/method/uae_erpgulf.uae_erpgulf.providers.suntech.adapter.suntech_webhook_listener"
        )

    # ------------------------------------------------------ incoming import
    def parse_incoming_invoice(self, invoice_json):
        """Suntech's invoice detail (GET /invoices/{id}/), or just its
        detail tree. Seller = the party that billed us."""
        detail = invoice_json.get("detail") if isinstance(invoice_json.get("detail"), dict) else invoice_json
        seller = detail.get("seller") if isinstance(detail.get("seller"), dict) else None
        if not seller or not isinstance(detail.get("lines"), list):
            return {}

        lines = []
        for line in detail.get("lines") or []:
            vat = (line.get("vat_info") or [{}])[0]
            qty = float(line.get("invoiced_quantity") or 1)
            base_qty = float(line.get("item_price_base_quantity") or 1)
            rate = float(line.get("item_net_price") or 0) / (base_qty or 1)
            lines.append({
                "name": line.get("item_name"),
                "description": line.get("item_description"),
                "qty": qty,
                "uom": "Nos",
                "rate": rate,
                "amount": float(line.get("line_net_amount") or qty * rate),
                "vat_rate": float(vat.get("vat_rate") if vat.get("vat_rate") is not None else 5),
            })

        payment = (detail.get("payment_instructions") or [{}])[0] or {}
        return {
            "supplier_name": seller.get("name"),
            "vat_number": seller.get("vat_identifier"),
            "posting_date": invoice_json.get("issue_date"),
            "due_date": detail.get("payment_due_date"),
            "currency": detail.get("invoice_currency_code") or "AED",
            "document_id": invoice_json.get("id"),
            "conversion_rate": detail.get("currency_exchange_rate"),
            "payment_means_code": payment.get("payment_means_type_code"),
            "lines": lines,
        }


# ---------------------------------------------------------------- webhook
def _verify_suntech_jwt(token):
    """Try every enabled Suntech settings row's Webhook Secret (HS256, §12.4).
    Returns the matching settings doc, or None."""
    import jwt

    rows = frappe.get_all(
        "E-Invoice Provider Settings",
        filters={"provider": SUNTECH_PROVIDER_NAME, "enabled": 1},
        pluck="name",
    )
    for name in rows:
        settings = frappe.get_doc("E-Invoice Provider Settings", name)
        secret = settings.get_password("webhook_secret", raise_exception=False)
        if not secret:
            continue
        try:
            jwt.decode(token, secret, algorithms=["HS256", "HS384", "HS512"], options={"verify_aud": False})
            return settings
        except Exception:
            continue
    return None


@frappe.whitelist(allow_guest=True)  # nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method
def suntech_webhook_listener():
    """Suntech webhook: {event, invoice_id, ...}. The payload is only a
    pointer (§12.2) - fetch the invoice for the real state."""
    raw_body = frappe.request.get_data(as_text=True)
    try:
        payload = json.loads(raw_body)
    except Exception:
        frappe.local.response["http_status_code"] = 400
        return {"received": False, "error": "invalid JSON"}

    auth = frappe.request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.startswith("Bearer ") else auth.strip()
    settings = _verify_suntech_jwt(token) if token else None
    if not settings:
        frappe.log_error(f"Suntech webhook rejected - JWT not verified. Body: {raw_body}", "Suntech Webhook Auth Failed")
        frappe.local.response["http_status_code"] = 401
        return {"received": False, "error": "signature verification failed"}

    event = payload.get("event")
    invoice_id = payload.get("invoice_id")
    adapter = SuntechAdapter(settings)

    body = {}
    try:
        response = adapter._get_invoice(invoice_id)
        body = response.json() if response.status_code == 200 else {}
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Suntech Webhook Fetch Error")

    reporting_status = adapter.get_status_from_document_status(body)

    frappe.get_doc({
        "doctype": "UAE E-Invoice Webhook Logs",
        "webhook_response": raw_body,
        "document_id": invoice_id,
        "participant_id": payload.get("organization_id"),
        "event_type": event,
        "reporting_status": reporting_status,
        "invoice_number": payload.get("invoice_name"),
    }).insert(ignore_permissions=True)

    if invoice_id and reporting_status:
        for doctype in ("Sales Invoice", "Purchase Invoice"):
            name = frappe.db.get_value(doctype, {"custom_document_id": invoice_id}, "name")
            if name:
                frappe.db.set_value(doctype, name, "custom_reporting_status", reporting_status)

    # A supplier invoice delivered to us -> keep it in UAE Incoming Invoices
    # so "Get FTA Incoming Invoices" on Purchase Invoice can import it.
    if event == "invoice.received" and body and body.get("direction") == 2:
        if not frappe.db.exists("UAE Incoming Invoices", {"document_id": invoice_id}):
            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": f"{body.get('invoice_number') or invoice_id}_suntech_incoming.json",
                "is_private": 1,
                "content": json.dumps(body, indent=2),
            }).insert(ignore_permissions=True)
            frappe.get_doc({
                "doctype": "UAE Incoming Invoices",
                "document_id": invoice_id,
                "incoming_invoice_file": file_doc.file_url,
                "status": "Not Submitted",
                "submit_response": json.dumps(body),
            }).insert(ignore_permissions=True)

    frappe.db.commit()  # nosemgrep: frappe-manual-commit
    return {"received": True, "processed": True}
