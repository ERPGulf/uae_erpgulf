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
SUNTECH_TIMEOUT = 60

# Header the Suntech portal puts the webhook JWT in (portal > Settings >
# Webhooks > Authentication > header name). Not "Authorization" - see
# suntech_webhook_listener.
SUNTECH_WEBHOOK_HEADER = "X-TCA-Token"

# Peppol scheme for UAE participants - used only when the stored Peppol ID
# doesn't carry its own scheme prefix (e.g. "0235:1234567890").
DEFAULT_ENDPOINT_SCHEME = "0235"

# PINT AE process identifiers (Suntech docs §9 / §11.2)
PROCESS_BILLING = {
    "profile_id": "urn:peppol:bis:billing",
    "customization_id": "urn:peppol:pint:billing-1@ae-1",
}
PROCESS_SELF_BILLING = {
    "profile_id": "urn:peppol:bis:selfbilling",
    "customization_id": "urn:peppol:pint:selfbilling-1@ae-1",
}

DISCREPANCY_CODES = {"DL8.61.1.A", "DL8.61.1.B", "DL8.61.1.C", "DL8.61.1.D", "DL8.61.1.E", "VD"}

# custom_legal_registration_identifier_type option -> BTAE-15/16 type code
LEGAL_REGISTRATION_TYPES = {
    "Commercial/Trade license": "TL",
    "Emirates ID": "EID",
    "Passport": "PAS",
    "Cabinet decision": "CD",
}

UOM_TO_UNECE = {
    "nos": "EA", "unit": "EA", "each": "EA", "pcs": "EA", "piece": "EA",
    "kg": "KGM", "kilogram": "KGM", "gram": "GRM", "gm": "GRM",
    "litre": "LTR", "liter": "LTR", "ltr": "LTR",
    "meter": "MTR", "metre": "MTR", "mtr": "MTR",
    "box": "BX", "pair": "PR", "dozen": "DZN", "hour": "HUR", "day": "DAY",
}

# invoice status (§14.1) -> custom_reporting_status
STATUS_TO_REPORTING = {1: "pending", 2: "reported", 3: "rejected", 4: "failed"}

TWO = Decimal("0.01")
SIX = Decimal("0.000001")


# ---------------------------------------------------------------- helpers
def _dec(value):
    return Decimal(str(value or 0))


def _money(value):
    return str(_dec(value).quantize(TWO, ROUND_HALF_UP))


def _qty(value):
    return str(_dec(value).quantize(SIX, ROUND_HALF_UP))


def _emirate_code(emirate_name):
    if not emirate_name:
        return None
    return {
        "abu dhabi": "AUH", "dubai": "DXB", "sharjah": "SHJ", "ajman": "AJM",
        "umm al quwain": "UAQ", "ras al khaimah": "RAK", "fujairah": "FUJ",
    }.get(emirate_name.strip().lower())


def _vat_category_code(label):
    """'S - Standard rated' -> 'S' (code before ' - ')."""
    if not label:
        return None
    code = label.split(" - ")[0].strip().upper()
    if code not in ("S", "Z", "E", "AE", "O", "N"):
        frappe.throw(_("Invalid VAT Category: {0}. Must be one of S, Z, E, AE, O, N.").format(label))
    return code


def _split_code(label):
    """'DL8.61.1.A-Cancellation' / '30 - Credit transfer' -> (code, text)."""
    raw = (label or "").strip()
    for sep in (" - ", "-"):
        if sep in raw:
            code, text = raw.split(sep, 1)
            return code.strip(), text.strip()
    return raw, raw


def _transaction_type_code(doc):
    """custom_invoice_transaction_type_code ('1XXXXXX : Free trade zone
    transaction') -> the 8-character 0/1 flag string BTAE-02 needs."""
    raw = (doc.get("custom_invoice_transaction_type_code") or "").split(":")[0].strip()
    bits = "".join("1" if c == "1" else "0" for c in raw)
    return (bits + "00000000")[:8]


def _endpoint(peppol_id):
    """'0235:1234567890' -> ('1234567890', '0235'); '1234567890' -> default scheme."""
    peppol_id = (peppol_id or "").strip()
    if ":" in peppol_id:
        scheme, value = peppol_id.split(":", 1)
        return value.strip(), scheme.strip()
    return peppol_id, DEFAULT_ENDPOINT_SCHEME


def _address_block(address_data, country_dict):
    country_code = None
    if address_data.country and address_data.country.lower() in country_dict:
        country_code = country_dict[address_data.country.lower()]
    if not country_code:
        frappe.throw(_("Address {0} has no recognised Country.").format(address_data.name))

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
    # Completed - fetch them later with the Get Document buttons or webhook.
    AUTO_FETCH_DOCUMENTS_ON_SUBMIT = False

    # ---------------------------------------------------------------- auth
    def get_api_url(self):
        """Base URL may be entered with or without /api/v1."""
        base = (self.get_base_url() or "").strip().rstrip("/")
        if not base:
            frappe.throw(_("Please enter Base URL on E-Invoice Provider Settings."))
        if not base.endswith("/api/v1"):
            base = f"{base}/api/v1"
        return base

    def _credentials(self):
        client_id = (self.settings.client_id or "").strip()
        client_secret = (self.settings.get_password("client_secret", raise_exception=False) or "").strip()
        if not client_id or not client_secret:
            frappe.throw(_("Please enter Client ID and Client Secret on E-Invoice Provider Settings."))
        return {"client_id": client_id, "client_secret": client_secret}

    def _token_response(self):
        response = requests.post(
            f"{self.get_api_url()}/oauth/token/",
            data=self._credentials(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=SUNTECH_TIMEOUT,
        )
        if not response.ok:
            frappe.throw(
                _("Suntech token request failed ({0}): {1}").format(
                    response.status_code, response.text or _("invalid Client ID / Client Secret")
                )
            )
        return response.json()

    def _fetch_token(self):
        data = self._token_response()
        access_token = data.get("access_token")
        if not access_token:
            frappe.throw(_("Access token not found in Suntech token response: {0}").format(data))

        # cache for the lifetime Suntech reports, minus a 30 s safety margin (§3.5)
        expires_in = data.get("expires_in")
        if isinstance(expires_in, (int, float)) and expires_in > 60:
            self.set_cached_token(access_token, expires_in_sec=int(expires_in) - 30)
        else:
            self.set_cached_token(access_token)
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
        """No organisation endpoint - the token response names the
        organisation the API client is bound to (§3.2)."""
        data = self._token_response()
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

        # Background check right after submit (runs on the worker, not the
        # scheduler): poll the status a few times until it is final.
        if response.status_code in (200, 201):
            frappe.enqueue(
                "uae_erpgulf.uae_erpgulf.providers.suntech.adapter.poll_suntech_status",
                queue="long",
                doctype=doctype,
                name=doc.name,
                enqueue_after_commit=True,
            )
        return response.status_code, response_data

    def _invoice_type_code(self, doctype, doc):
        if doctype == "Purchase Invoice":
            return "261" if doc.is_return else "389"
        out_of_scope = _vat_category_code(doc.get("custom_vat_category")) == "O"
        if doc.is_return:
            return "81" if out_of_scope else "381"
        return "480" if out_of_scope else "380"

    def _build_payload(self, doctype, doc):
        type_code = self._invoice_type_code(doctype, doc)
        is_credit = type_code in ("381", "81", "261")
        country_dict = country_code_mapping()

        if doctype == "Purchase Invoice":
            seller = self._party_from_supplier(doc, country_dict)
            buyer = self._party_from_company(doc, country_dict, is_seller=False)
            process_control = PROCESS_SELF_BILLING
        else:
            seller = self._party_from_company(doc, country_dict, is_seller=True)
            buyer = self._party_from_customer(doc, country_dict)
            process_control = PROCESS_BILLING

        built = self._build_lines(doc)
        currency = (doc.currency or "").upper()
        company_currency = (frappe.get_cached_value("Company", doc.company, "default_currency") or "AED").upper()
        conversion_rate = _dec(doc.conversion_rate or 1)

        detail = {
            "transaction_type_code": _transaction_type_code(doc),
            "invoice_currency_code": currency,
            "issue_time": self._issue_time(doc),
            "process_control": dict(process_control),
            "seller": seller,
            "buyer": buyer,
            "totals": self._totals(doc, built, conversion_rate),
            "vat_breakdowns": built["vat_breakdowns"],
            "lines": built["lines"],
        }
        if built["allowances"]:
            detail["allowances"] = built["allowances"]

        if currency != company_currency:
            detail["tax_currency_code"] = company_currency
            detail["currency_exchange_rate"] = _qty(conversion_rate)

        # optional references straight from the document
        if doc.get("po_no"):
            detail["purchase_order_reference"] = doc.po_no
        if doc.get("project"):
            detail["project_reference"] = doc.project
        if doc.get("cost_center"):
            detail["buyer_accounting_reference"] = doc.cost_center
        if doc.get("custom_invoice_note") or doc.get("remarks"):
            detail["invoice_note"] = doc.get("custom_invoice_note") or doc.get("remarks")

        payment_instructions = self._payment_instructions(doctype, doc)
        if payment_instructions:
            detail["payment_instructions"] = payment_instructions

        if is_credit:
            detail.update(self._credit_note_fields(doctype, doc))
        else:
            if doc.get("due_date"):
                detail["payment_due_date"] = str(doc.due_date)

        return {
            "name": doc.get("title") or doc.name,
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
        raw = doc.get("custom_credit_note_reason_code")
        if not raw:
            frappe.throw(_("Please select a Credit Note Reason Code before submitting this return."))
        code, _text = _split_code(raw)
        if code not in DISCREPANCY_CODES:
            frappe.throw(
                _("Credit Note Reason Code {0} isn't one Suntech accepts ({1}).").format(
                    code, ", ".join(sorted(DISCREPANCY_CODES))
                )
            )

        fields = {"discrepancy_response_code": code}

        # VD (void) credit notes carry no preceding reference (§10, §11.1)
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
    def _base_party(self, name, tax_id, peppol_id, label):
        if not peppol_id:
            frappe.throw(_("{0} has no Peppol ID set.").format(label))
        value, scheme = _endpoint(peppol_id)
        return {
            "name": name,
            "vat_identifier": tax_id or None,
            "tax_scheme": "VAT",
            "electronic_address": value,
            "electronic_address_scheme": scheme,
        }

    def _party_from_company(self, doc, country_dict, is_seller):
        from frappe.contacts.doctype.address.address import get_default_address

        company = frappe.get_doc("Company", doc.company)
        address_name = (
            doc.get("company_address") if doc.doctype == "Sales Invoice" else doc.get("billing_address")
        ) or get_default_address("Company", company.name)
        if not address_name:
            frappe.throw(_("Company {0} has no Address linked to it.").format(company.name))
        address = frappe.get_doc("Address", address_name)

        # Our Peppol electronic address must be the organisation's 10-digit TIN
        # as registered with Suntech (Participant ID on the settings row).
        tin, _scheme = _endpoint(self.settings.participant_id)
        if not (tin.isdigit() and len(tin) == 10):
            frappe.throw(
                _("Participant ID (Peppol) on E-Invoice Provider Settings {0} must be your 10-digit "
                  "TIN (e.g. 1354276574), not '{1}'.").format(self.settings.name, self.settings.participant_id)
            )

        party = self._base_party(
            company.company_name,
            # TRN registered with Suntech (settings row), else the Company's Tax ID
            self.settings.get("trn") or doc.get("company_tax_id") or company.tax_id,
            self.settings.participant_id,
            _("E-Invoice Provider Settings (Participant ID)"),
        )
        party.update(_address_block(address, country_dict))
        self._add_legal_registration(party, company, required=is_seller)
        return party

    def _party_from_customer(self, doc, country_dict):
        customer = frappe.get_doc("Customer", doc.customer)
        address_name = doc.get("customer_address") or customer.get("customer_primary_address")
        if not address_name:
            frappe.throw(_("Customer address not found for {0}").format(doc.customer))
        address = frappe.get_doc("Address", address_name)

        party = self._base_party(
            doc.get("customer_name") or customer.customer_name,
            doc.get("tax_id") or customer.tax_id,
            customer.get("custom_peppol_id"),
            _("Customer {0}").format(doc.customer),
        )
        party.update(_address_block(address, country_dict))
        if doc.get("contact_display"):
            party["contact_point"] = doc.contact_display
        self._add_legal_registration(party, customer, required=False)
        if customer.get("custom_fz_beneficiary_id"):
            party["beneficiary_identifier"] = customer.custom_fz_beneficiary_id
        return party

    def _party_from_supplier(self, doc, country_dict):
        supplier = frappe.get_doc("Supplier", doc.supplier)
        address_name = doc.get("supplier_address") or supplier.get("supplier_primary_address")
        if not address_name:
            frappe.throw(_("Supplier address not found for {0}").format(doc.supplier))
        address = frappe.get_doc("Address", address_name)

        party = self._base_party(
            doc.get("supplier_name") or supplier.supplier_name,
            doc.get("tax_id") or supplier.tax_id,
            supplier.get("custom_peppol_id"),
            _("Supplier {0}").format(doc.supplier),
        )
        party.update(_address_block(address, country_dict))
        if doc.get("contact_display"):
            party["contact_point"] = doc.contact_display
        # self-billing: the supplier is the seller, so its registration is required
        self._add_legal_registration(party, supplier, required=True)
        return party

    def _add_legal_registration(self, party, party_doc, required=False):
        """Legal registration (IBT-030 / IBT-047) from the party's own fields:
        custom_legal_registration_identifier_type, custom_trade_license_number,
        custom_legal_registration_authority."""
        number = (party_doc.get("custom_trade_license_number") or "").strip()
        reg_type = party_doc.get("custom_legal_registration_identifier_type")

        if not number:
            if required:
                frappe.throw(
                    _("{0} {1} has no Legal Registration Number ({2}) - Suntech requires the seller's "
                      "legal registration identifier (IBT-030).").format(
                        _(party_doc.doctype), party_doc.name, reg_type or _("Commercial/Trade license")
                    )
                )
            return

        type_code = LEGAL_REGISTRATION_TYPES.get(reg_type, "TL")
        party["legal_registration_identifier"] = number
        party["legal_registration_identifier_type"] = type_code
        if party_doc.get("custom_legal_registration_authority"):
            party["authority_name"] = party_doc.custom_legal_registration_authority
        if type_code == "TL" and not party.get("authority_name"):
            frappe.throw(
                _("{0} {1} has a Trade License but no Legal Registration Authority - Suntech "
                  "requires the issuing authority for trade licences.").format(
                    _(party_doc.doctype), party_doc.name
                )
            )

        # Passport needs the issuing country (ISO alpha-2): the party's
        # Passport Issuing Country field if it has one, else its address country.
        if type_code == "PAS":
            issuing_country = party_doc.get("custom_passport_issuing_country")
            if issuing_country:
                code = country_code_mapping().get(issuing_country.strip().lower())
                if not code:
                    frappe.throw(
                        _("Passport Issuing Country {0} on {1} {2} isn't a recognised country.").format(
                            issuing_country, _(party_doc.doctype), party_doc.name
                        )
                    )
            else:
                code = party.get("country_code")
            party["passport_issuing_country_code"] = code

    # --------------------------------------------------------------- lines
    def _item_tax(self, doc, item):
        """VAT category / rate / exemption for one item: Item Tax Template
        first, then the invoice's own VAT category and tax row."""
        category = doc.get("custom_vat_category")
        exemption = doc.get("custom_vat_exemption_reason_code")
        rate = doc.taxes[0].rate if doc.get("taxes") else 0

        if item.get("item_tax_template"):
            template = frappe.get_cached_doc("Item Tax Template", item.item_tax_template)
            category = template.get("custom_vat_category") or category
            exemption = template.get("custom_vat_exemption_reason_code") or exemption
            if template.taxes:
                rate = template.taxes[0].tax_rate

        if not category:
            frappe.throw(_("Set a VAT Category on {0} or on Item {1}'s Item Tax Template.").format(
                doc.name, item.item_code))
        return _vat_category_code(category), _dec(rate), exemption

    def _build_lines(self, doc):
        """Lines carry the item amount before invoice discount; the invoice
        discount (item amount - item net_amount) goes out as document-level
        allowances, per VAT category. Prices that include tax use net values."""
        tax_inclusive = any(t.get("included_in_print_rate") for t in (doc.get("taxes") or []))
        conversion_rate = _dec(doc.conversion_rate or 1)

        lines, allowances = [], {}
        breakdown = {}
        line_total = Decimal("0")

        for idx, item in enumerate(doc.items, 1):
            vat_code, rate, exemption = self._item_tax(doc, item)
            qty = abs(_dec(item.qty))
            net_amount = abs(_dec(item.net_amount)).quantize(TWO, ROUND_HALF_UP)
            gross_amount = net_amount if tax_inclusive else abs(_dec(item.amount)).quantize(TWO, ROUND_HALF_UP)
            price = (gross_amount / qty) if qty else Decimal("0")
            line_total += gross_amount

            vat_info = {"vat_category_code": vat_code, "vat_rate": _money(rate), "tax_scheme": "VAT"}
            if vat_code == "E":
                if not exemption:
                    frappe.throw(_("Item {0} is VAT-exempt but has no VAT Exemption Reason Code.").format(
                        item.item_code))
                ex_code, ex_text = _split_code(exemption)
                vat_info["vat_exemption_reason_code"] = ex_code
                vat_info["vat_exemption_reason_text"] = ex_text

            uom = (item.get("uom") or "").strip()
            line = {
                "line_id": str(item.get("idx") or idx),
                "invoiced_quantity": _qty(qty),
                "invoiced_quantity_unit_of_measure_code": UOM_TO_UNECE.get(uom.lower(), uom.upper() or "EA"),
                "line_net_amount": _money(gross_amount),
                "item_net_price": _qty(price),
                "item_price_base_quantity": _qty(1),
                "item_name": item.item_name,
                "item_description": strip_html(item.get("description") or "").strip() or item.item_name,
                "line_amount_in_aed": _money(gross_amount * conversion_rate),
                "vat_line_amount_in_aed": _money(gross_amount * rate / 100 * conversion_rate),
                "vat_info": [vat_info],
            }
            if item.get("item_code"):
                line["item_sellers_identifier"] = item.item_code
            if item.get("purchase_order"):
                line["purchase_order_reference"] = item.purchase_order
            if item.get("cost_center"):
                line["buyer_accounting_reference"] = item.cost_center

            item_type = (item.get("custom_item_type_codes") or "").split(" - ")[0].strip().upper()
            if item_type in ("G", "S", "B"):
                line["item_type"] = item_type
            if item.get("custom_hs_code_"):
                line["classifications"] = [
                    {"classification_identifier": item.custom_hs_code_, "classification_identifier_scheme": "HS"}
                ]
            if item.get("custom_sac_code"):
                line["service_accounting_codes"] = [{"code": item.custom_sac_code, "scheme_identifier": "SAC"}]
            lines.append(line)

            key = (vat_code, rate)
            row = breakdown.setdefault(key, {"taxable": Decimal("0"), "vat_info": vat_info})
            row["taxable"] += net_amount

            discount = gross_amount - net_amount
            if discount:
                allowances[key] = allowances.get(key, Decimal("0")) + discount

        # VAT per category; the last category absorbs any rounding difference
        # so the breakdown always adds up to the invoice's own tax total.
        doc_vat = abs(_dec(doc.get("total_taxes_and_charges"))).quantize(TWO, ROUND_HALF_UP)
        vat_breakdowns, vat_total = [], Decimal("0")
        keys = list(breakdown)
        for i, key in enumerate(keys):
            vat_code, rate = key
            row = breakdown[key]
            tax = (row["taxable"] * rate / 100).quantize(TWO, ROUND_HALF_UP)
            if i == len(keys) - 1 and doc_vat and abs(doc_vat - (vat_total + tax)) < Decimal("1"):
                tax = doc_vat - vat_total
            vat_total += tax
            entry = {
                "taxable_amount": _money(row["taxable"]),
                "tax_amount": _money(tax),
                "vat_category_code": vat_code,
                "tax_scheme_code": "VAT",
                "vat_category_rate": _money(rate),
            }
            if vat_code == "E":
                entry["vat_exemption_reason_code"] = row["vat_info"].get("vat_exemption_reason_code")
                entry["vat_exemption_reason_text"] = row["vat_info"].get("vat_exemption_reason_text")
            vat_breakdowns.append(entry)

        allowance_rows = [
            {
                "amount": _money(amount),
                "vat_category_code": vat_code,
                "vat_rate": _money(rate),
                "tax_scheme_code": "VAT",
                "reason": _("Discount"),
                "reason_code": "95",
            }
            for (vat_code, rate), amount in allowances.items()
        ]

        return {
            "lines": lines,
            "allowances": allowance_rows,
            "vat_breakdowns": vat_breakdowns,
            "line_total": line_total,
            "allowance_total": sum(allowances.values(), Decimal("0")),
            "vat_total": vat_total,
            "tax_inclusive": tax_inclusive,
        }

    def _totals(self, doc, built, conversion_rate):
        line_total = built["line_total"]
        allowance_total = built["allowance_total"]
        without_vat = line_total - allowance_total
        with_vat = without_vat + built["vat_total"]

        rounding = _dec(doc.get("rounding_adjustment"))
        if doc.get("is_return"):
            rounding = -rounding
        if doc.get("is_pos"):
            paid = abs(_dec(doc.get("paid_amount"))) - abs(_dec(doc.get("change_amount")))
        else:
            paid = abs(_dec(doc.get("total_advance")))
        due = with_vat + rounding - paid

        return {
            "sum_of_invoice_line_net_amount": _money(line_total),
            "sum_of_allowances_on_document_level": _money(allowance_total),
            "sum_of_charges_on_document_level": _money(0),
            "invoice_total_amount_without_vat": _money(without_vat),
            "invoice_total_vat_amount": _money(built["vat_total"]),
            "invoice_total_amount_with_vat": _money(with_vat),
            "paid_amount": _money(paid),
            "rounding_amount": _money(rounding),
            "amount_due_for_payment": _money(due),
            "invoice_total_amount_with_vat_in_aed": _money(with_vat * conversion_rate),
            "tax_included_indicator": built["tax_inclusive"],
        }

    def _payment_instructions(self, doctype, doc):
        """Purchase Invoice: its own Payment Means Codes field. Sales Invoice:
        the Payment Means Code on the first Mode of Payment used."""
        raw = doc.get("custom_payment_means_codes")
        if not raw and doctype == "Sales Invoice":
            for row in doc.get("payments") or []:
                if row.mode_of_payment:
                    raw = frappe.get_cached_value("Mode of Payment", row.mode_of_payment, "custom_payment_means_codes")
                    if raw:
                        break
        if not raw:
            return None

        code, text = _split_code(raw)
        entry = {"payment_means_type_code": code}
        if text and text != code:
            entry["payment_means_text"] = text

        bank_account = doc.get("company_bank_account") if doctype == "Sales Invoice" else doc.get("supplier_bank_account")
        if bank_account:
            bank = frappe.get_cached_doc("Bank Account", bank_account)
            account_no = bank.get("iban") or bank.get("bank_account_no")
            if account_no:
                entry["payment_account_identifier"] = account_no
                if bank.get("iban"):
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

        _attach_documents_if_ready(doctype, doc.name, body)
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
    def _webhook_portal_message(self):
        return _(
            "Suntech webhooks are configured in the Suntech portal (Settings > Webhooks), not through "
            "the API. Use this row's Webhook URL as the endpoint there, choose HS256 JWT auth, and put "
            "the same shared secret in this row's Webhook Secret field."
        )

    def register_webhook(self):
        frappe.throw(self._webhook_portal_message())

    def get_subscription(self):
        frappe.throw(self._webhook_portal_message())

    def get_webhook_deliveries(self):
        frappe.throw(self._webhook_portal_message())

    def get_webhook_listener_url(self):
        return frappe.utils.get_url(
            "/api/method/uae_erpgulf.uae_erpgulf.providers.suntech.adapter.suntech_webhook_listener"
        )

    # ------------------------------------------------------ incoming import
    def parse_incoming_invoice(self, invoice_json):
        """Suntech's invoice detail (GET /invoices/{id}/), or just its detail
        tree. Seller = the party that billed us."""
        detail = invoice_json.get("detail") if isinstance(invoice_json.get("detail"), dict) else invoice_json
        seller = detail.get("seller") if isinstance(detail.get("seller"), dict) else None
        if not seller or not isinstance(detail.get("lines"), list):
            return {}

        unece_to_uom = {}
        for uom, code in UOM_TO_UNECE.items():
            unece_to_uom.setdefault(code, uom.title())
        unece_to_uom["EA"] = "Nos"

        lines = []
        for line in detail.get("lines") or []:
            vat = (line.get("vat_info") or [{}])[0]
            qty = float(line.get("invoiced_quantity") or 1)
            base_qty = float(line.get("item_price_base_quantity") or 1)
            rate = float(line.get("item_net_price") or 0) / (base_qty or 1)
            unit = line.get("invoiced_quantity_unit_of_measure_code")
            lines.append({
                "name": line.get("item_name"),
                "description": line.get("item_description"),
                "qty": qty,
                "uom": unece_to_uom.get(unit, unit or "Nos"),
                "rate": rate,
                "amount": float(line.get("line_net_amount") or qty * rate),
                "vat_rate": float(vat.get("vat_rate") or 0),
            })

        payment = (detail.get("payment_instructions") or [{}])[0] or {}
        return {
            "supplier_name": seller.get("name"),
            "vat_number": seller.get("vat_identifier"),
            "posting_date": invoice_json.get("issue_date"),
            "due_date": detail.get("payment_due_date"),
            "currency": detail.get("invoice_currency_code"),
            "document_id": invoice_json.get("id"),
            "conversion_rate": detail.get("currency_exchange_rate"),
            "payment_means_code": payment.get("payment_means_type_code"),
            "lines": lines,
        }


# ------------------------------------------------- automatic XML / PDF
def _attach_documents_if_ready(doctype, invoice_name, body):
    """Once Suntech has produced the signed XML / PDF (their S3 paths are on
    the invoice detail - the PDF only once the invoice is Completed), attach
    whichever one the ERPNext invoice doesn't have yet. Failures are logged,
    never raised, so a status check or webhook is never interrupted."""
    if not isinstance(body, dict) or not invoice_name:
        return

    from uae_erpgulf.uae_erpgulf.attach import get_document_pdf, get_document_xml

    current = frappe.db.get_value(
        doctype, invoice_name, ["custom_document_xml", "custom_document_pdf"], as_dict=True
    ) or {}

    for path_field, attached_field, fetch_fn in (
        ("invoice_xml_location_path", "custom_document_xml", get_document_xml),
        ("pdf_location_path", "custom_document_pdf", get_document_pdf),
    ):
        if not body.get(path_field) or current.get(attached_field):
            continue
        messages_before = len(frappe.local.message_log)
        try:
            fetch_fn(doctype, invoice_name)
        except Exception:
            # attach.py already wrote the Error Log; drop its popup message
            del frappe.local.message_log[messages_before:]


def poll_suntech_status(doctype, name, attempts=6, wait=20):
    """Background job enqueued by submit_invoice: checks the status every
    `wait` seconds until it is final (reported / rejected / failed).
    get_document_status also attaches the XML / PDF when ready."""
    import time

    for _i in range(attempts):
        time.sleep(wait)
        try:
            doc = frappe.get_doc(doctype, name)
            if not doc.get("custom_document_id"):
                continue
            settings = frappe.get_doc(
                "E-Invoice Provider Settings",
                {"company": doc.company, "provider": SUNTECH_PROVIDER_NAME, "enabled": 1},
            )
            result = SuntechAdapter(settings).get_document_status(doctype, doc)
            status = (result.get("reporting_status") or "").lower()
            if status:
                frappe.db.set_value(doctype, name, "custom_reporting_status", status)
                frappe.db.commit()  # nosemgrep: frappe-manual-commit
            if status in ("reported", "rejected", "failed"):
                break
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"Suntech Poll Error - {name}")
            break


def sync_pending_suntech_invoices():
    """Scheduled (hooks.py): for submitted Suntech invoices that aren't
    finished yet - not reported, or XML / PDF still missing - refresh the
    status and attach the XML / PDF as soon as Suntech has them."""
    companies = frappe.get_all(
        "Company", filters={"custom_accredited_service_providers": SUNTECH_PROVIDER_NAME}, pluck="name"
    )
    if not companies:
        return

    since = frappe.utils.add_days(frappe.utils.nowdate(), -7)
    for doctype in ("Sales Invoice", "Purchase Invoice"):
        rows = frappe.get_all(
            doctype,
            filters={
                "docstatus": 1,
                "company": ["in", companies],
                "custom_document_id": ["is", "set"],
                "posting_date": [">=", since],
            },
            or_filters={
                "custom_reporting_status": ["not in", ["reported", "rejected", "failed"]],
                "custom_document_xml": ["is", "not set"],
                "custom_document_pdf": ["is", "not set"],
            },
            pluck="name",
            limit=50,
        )
        for name in rows:
            try:
                doc = frappe.get_doc(doctype, name)
                settings = frappe.get_doc(
                    "E-Invoice Provider Settings",
                    {"company": doc.company, "provider": SUNTECH_PROVIDER_NAME, "enabled": 1},
                )
                result = SuntechAdapter(settings).get_document_status(doctype, doc)
                if result.get("reporting_status"):
                    frappe.db.set_value(doctype, name, "custom_reporting_status", result["reporting_status"])
                frappe.db.commit()  # nosemgrep: frappe-manual-commit
            except Exception:
                frappe.log_error(frappe.get_traceback(), f"Suntech Status Sync Error - {name}")


# ---------------------------------------------------------------- webhook
def _verify_suntech_jwt(token):
    """Try each enabled Suntech settings row's Webhook Secret (HMAC JWT, §12.4).
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

    # The JWT must NOT come in the Authorization header: Frappe treats any
    # "Authorization: Bearer ..." as its own login token and rejects the
    # request with 401 before this function runs. In the Suntech portal set
    # the auth header name to SUNTECH_WEBHOOK_HEADER and leave the scheme empty.
    auth = (frappe.request.headers.get(SUNTECH_WEBHOOK_HEADER) or "").strip()
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else auth
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

    if invoice_id:
        for doctype in ("Sales Invoice", "Purchase Invoice"):
            name = frappe.db.get_value(doctype, {"custom_document_id": invoice_id}, "name")
            if name:
                if reporting_status:
                    frappe.db.set_value(doctype, name, "custom_reporting_status", reporting_status)
                _attach_documents_if_ready(doctype, name, body)

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