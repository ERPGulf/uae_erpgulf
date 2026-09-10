"""Marmin AI Software Design LLC adapter.

Built from two sources: the one docs page we've seen
(https://docs.ae.marmin.ai/docs/2026-05-07/flow/businesses/sale-documents/sale-invoices/create,
covering ONLY "create a sale invoice"), and a follow-up email from Marmin
with sandbox config: Client ID, Client Secret, Business Profile ID, API
Version, Base URL, and a Token Endpoint (GET .../auth/token). Put the
Client ID/Client Secret/Business Profile ID (as Participant ID)/Base URL
from that email onto the company's E-Invoice Provider Settings row -
that's what this adapter reads.

Everything below other than auth, submit_invoice and get_participant_details
still has no verified docs page, so it raises a clear error explaining
exactly what's missing instead of guessing a URL or payload shape. Fill
each one in - and delete its "not implemented yet" throw - once you have
the matching docs page for it, the same way those three were filled in.

Note on get_participant_details specifically: Marmin has no "participant"
concept at all - their docs are organized around "Business Profiles"
instead (Party Management > Business Profiles > Retrieve a Business
Profile, GET /api/business-profiles/{profileId}). It's the same underlying
idea (a registered legal entity + its PEPPOL endpoint), just named
differently, which is exactly why the doctype field for it is called the
provider-neutral "Participant ID" rather than something Flick-specific -
every adapter reads/writes that same field, under whatever name its own
ASP calls it.

The exact token flow (confirmed by Marmin, not guessed): HMAC-SHA256-sign
the Client ID using the Client Secret as the key, base64-encode that
signature, then GET /auth/token?client_id=<CLIENT_ID> with that signature
in an x-marmin-signature header. That's what _fetch_token does below.
"""

import base64
import hmac
import hashlib
import json

import frappe
import requests
from frappe import _

from uae_erpgulf.uae_erpgulf.providers.base import BaseAdapter
from uae_erpgulf.uae_erpgulf.json_einvoice import (
    get_vat_category_code,
    get_uae_emirate_code,
    get_invoice_type_code,
)
from uae_erpgulf.uae_erpgulf.country_code import country_code_mapping

MARMIN_API_VERSION = "20260507"  # from the 2026-05-07 docs page

# profile_execution_id is NOT a docname or any kind of ID we generate - it's an
# 8-digit flag string (each digit 0 or 1) from Marmin's docs, one position per
# special scenario (FTZ, deemed supply, profit margin scheme, summary invoice,
# continuous supply, disclosed agent billing, e-commerce supply, exports).
# "00000000" means none of those apply - a normal invoice, which is the only
# case this adapter builds so far. If you need one of those scenarios, flip
# the matching digit rather than adding a new constant.
MARMIN_PROFILE_EXECUTION_ID_STANDARD = "00000000"

# payment_means is mandatory and Marmin only accepts these codes: 1, 10, 20,
# 21, 30, 49, 54, 55, 68 - a different (mostly overlapping) list from the one
# Flick/PEPPOL's own get_payment_means() checks against (which also allows
# 48/57/58), so a Mode of Payment set up only for Flick may not carry a code
# Marmin accepts. "1" (UNCL4461 "Instrument not defined") is the fallback
# used only when an invoice has no Payments row or no Mode of Payment code
# configured at all, so a bare test invoice still submits.
MARMIN_DEFAULT_PAYMENT_MEANS_CODE = "1"
MARMIN_APPROVED_PAYMENT_MEANS_CODES = {"1", "10", "20", "21", "30", "49", "54", "55", "68"}

# PEPPOL endpoint scheme id - Marmin's docs say "typically 0235 for UAE",
# same network Flick's custom_peppol_id values already come from.
MARMIN_ENDPOINT_SCHEME_ID_UAE = "0235"

# unit_code must be a UN/ECE Rec 20/21 code (EA, KGM, LTR, ...), not ERPNext's
# own UOM name - this maps the common ones and falls back to "EA" (each) for
# anything unmapped. Extend this if you sell in units it doesn't cover yet.
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
    # Marmin's payload is built straight from the Sales Invoice doc
    # (_build_invoice_payload below), never from the shared
    # "<invoice>_uae_invoice.json" file - so there's no reason to generate
    # or attach that Flick-shaped file for a Marmin-configured company at
    # all. See USES_SHARED_INVOICE_JSON on BaseAdapter.
    USES_SHARED_INVOICE_JSON = False

    # Marmin's XML is generated asynchronously some time after an invoice is
    # accepted (a "XML not generated for document ..." response right after
    # submit is normal, not a bug), and Marmin has no documented PDF endpoint
    # at all yet - so don't auto-fetch either one right after submit_invoice()
    # the way the base class does for Flick. Leave that to the existing
    # "Get Document Status"/"Get XML" buttons, clicked later once Marmin has
    # actually finished processing the document.
    AUTO_FETCH_DOCUMENTS_ON_SUBMIT = False

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

        # expires_in isn't confirmed in any Marmin docs page we've seen - this
        # is a best-effort read of the same field name OAuth2-style responses
        # commonly use, in case Marmin's token endpoint includes it. Falls
        # back to the base class's default (55 minutes) when it's absent, so
        # nothing changes for the common case where Marmin doesn't send it.
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
        """GET /api/business-profiles/{profileId}

        Marmin doesn't have a separate "participant" concept the way Flick
        does - a Business Profile IS the registered party/PEPPOL endpoint,
        confirmed from their Party Management > Business Profiles docs page.
        So this reads the same ID already stored in Participant ID (reused
        as business_profile_id everywhere else in this adapter too)."""
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

    def get_document_status(self, doctype, doc):
        """GET /api/sales-invoices/{id}/peppol-status-logs - confirmed docs
        page (sandbox example: curl .../api/sales-invoices/{id}/peppol-status-logs
        -H "Authorization: Bearer <token>"). Response is JSON - a log of this
        document's PEPPOL exchange/reporting status entries, which is exactly
        what the "Get Document Status" button (already in the UI, wired to
        the generic get_document_status in verify_token.py) is for: click it
        later, once Marmin has actually finished processing the document,
        instead of this adapter guessing at a status right after submit.

        {id} is MARMIN's OWN invoice id, same as get_document_xml above - read
        out of the saved submit response, not doc.name/Business Profile ID.

        Marmin's docs example for this one only shows an Authorization
        header, not X-MARMIN-VERSION (unlike every other endpoint we've
        confirmed for them) - still sending it anyway via get_auth_headers()
        for consistency, since nothing in the docs says an extra header here
        is rejected. If this endpoint ever 400s specifically because of that
        header, that's the first thing to try removing."""
        if not doc.custom_submit_response:
            frappe.throw(_("Submit response not found in Invoice"))

        response_data = json.loads(doc.custom_submit_response)
        document_id = response_data.get("id") or response_data.get("data", {}).get("id")
        if not document_id:
            frappe.throw(_("Marmin invoice id not found in submit response"))

        base_url = self.get_base_url()
        url = f"{base_url}/api/sales-invoices/{document_id}/peppol-status-logs"
        headers = self.get_auth_headers()

        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            try:
                return response.json()
            except Exception:
                return response.text

        frappe.throw(_("Marmin API Error: {0}").format(response.text))

    def get_document_xml(self, doctype, doc):
        """GET /api/sales-invoices/{id}/xml - confirmed docs page (sandbox
        example: curl .../api/sales-invoices/{id}/xml -H "Authorization:
        Bearer <token>" -H "X-MARMIN-VERSION: ..." -o invoice.xml). Response
        is raw XML text, not JSON - unlike get_participant_details above.

        {id} here is MARMIN's OWN invoice id - a UUID it assigns once the
        invoice is accepted (not this Sales Invoice's own name/
        document_number, and not the Business Profile ID either) - so it
        has to be read back out of the saved submit response rather than
        off doc directly. Checked at the top level first (response_data["id"]
        - matches the shape of Marmin's fuller invoice-object reference
        example, where "id" sits at the top, not nested), falling back to
        a Flick-style nested ["data"]["id"] in case Marmin's real response
        turns out to nest it after all."""
        if not doc.custom_submit_response:
            frappe.throw(_("Submit response not found in Invoice"))

        response_data = json.loads(doc.custom_submit_response)
        document_id = response_data.get("id") or response_data.get("data", {}).get("id")
        if not document_id:
            frappe.throw(_("Marmin invoice id not found in submit response"))

        base_url = self.get_base_url()
        url = f"{base_url}/api/sales-invoices/{document_id}/xml"
        headers = self.get_auth_headers()

        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.text

        frappe.throw(_("Marmin API Error: {0}").format(response.text))

    def get_document_pdf(self, doctype, doc):
        frappe.throw(_("Marmin doesn't have a documented PDF endpoint yet."))

    # ---- webhook: dashboard-only, confirmed from
    # docs.ae.marmin.ai/.../integration/webhooks/* - there is no API for any
    # of this. Subscribing, viewing the subscription, and regenerating the
    # signing secret are all done in the Marmin Web Application's Developer
    # Dashboard > Webhooks tab, and every one of those actions is gated by
    # OTP 2FA sent to your registered email. So these three methods can't be
    # turned into real API calls the way Flick's were - the fix here is a
    # clear message telling you what to do instead, not a request to some
    # endpoint that doesn't exist.
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

    # ---- invoices: the one thing we do have real docs for ----
    def submit_invoice(self, doctype, doc, json_data):
        """POST /api/sales-invoices/{business_profile_id}

        NOTE: Sales Invoice only for now - the docs page we have is
        specifically "sale-invoices/create". Purchase Invoice needs its own
        Marmin docs page before this can support it.
        """
        if doctype != "Sales Invoice":
            frappe.throw(_("Marmin adapter only supports Sales Invoice submission so far."))
        if doc.is_return:
            # get_invoice_type_code() (reused below) would return 381/81 for
            # a credit note, but those codes have only been confirmed against
            # Marmin's sale-invoices/create endpoint - their docs list a
            # separate sale.credit_note.create event, implying credit notes
            # go through their own, not-yet-documented endpoint. Throwing
            # here beats silently sending a credit note through the invoice
            # endpoint and guessing whether Marmin accepts it there.
            frappe.throw(
                _("Marmin credit note submission isn't implemented yet - no docs page for it.")
            )

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

        # This is the ONLY JSON Marmin actually receives - it has nothing to
        # do with the Flick-shaped .json file attached to the Sales Invoice
        # (that one's built once for every provider and only Flick's adapter
        # uses it). save_outgoing_payload() (BaseAdapter) attaches it as its
        # own file on the invoice, under the same Attachments list, so it's
        # visible right after every submit attempt - success or failure.
        self.save_outgoing_payload(doc, payload)

        response = requests.post(url, headers=headers, json=payload, timeout=120)

        try:
            response_data = response.json()
        except Exception:
            response_data = response.text

        return response.status_code, response_data

    def _build_invoice_payload(self, doc):
        """Maps a Sales Invoice to Marmin's flat JSON shape, per Marmin's own
        schema (docs.ae.marmin.ai/.../sale-invoices/create) - this replaces an
        earlier version that guessed field names (item_name/unit_price/
        line_amount, and profile_execution_id as this row's docname) and got
        a 400 back listing every one of them as wrong or missing. Only the
        fields we're confident about are filled in here - Marmin's docs list
        30+ further optional fields (delivery info, payment means,
        allowances, etc.) that aren't mapped yet.

        NOTE: this builds straight from the Sales Invoice document (doc),
        not from json_data - json_data is the PEPPOL/UBL-style JSON built for
        Flick, and Marmin's payload shape is a different, flat JSON, so
        json_data isn't reused here (it's still accepted as a parameter to
        match the shared submit_invoice interface every adapter uses).

        invoice_type_code was a hardcoded "380" before - now it calls Flick's
        own get_invoice_type_code(doc) (json_einvoice.py), which returns "480"
        instead whenever custom_vat_category is "O - Not subject to VAT",
        matching the same "380 or 480" Marmin's docs describe, instead of
        always claiming every invoice is standard-rated.
        """
        default_vat_category = doc.custom_vat_category
        default_vat_rate = doc.taxes[0].rate if doc.taxes else 0
        default_exemption_label = doc.custom_vat_exemption_reason_code

        return {
            "profile_execution_id": MARMIN_PROFILE_EXECUTION_ID_STANDARD,
            "document_number": doc.name,
            "issue_date": str(doc.posting_date),
            "invoice_type_code": get_invoice_type_code(doc),
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

    def _build_payment_means(self, doc):
        """Build payment_means from this invoice's own Payments table.

        json_einvoice.py has TWO functions both named get_payment_means -
        one reading a flat mode_of_payment + company_bank_account (dead
        code: Python keeps only the last def with a given name, so that
        version never actually runs, which is also why it can reference a
        mode_of_payment field that doesn't exist on Sales Invoice without
        ever throwing), and the real one actually called from
        build_uae_invoice_json, which loops sales_invoice_doc.payments and
        reads bank details off each row's Mode of Payment -> Accounts
        table. This mirrors that real one.

        Falls back to MARMIN_DEFAULT_PAYMENT_MEANS_CODE only when the
        invoice has no Payments row, or the row's Mode of Payment has no
        code configured - not a silent default when data IS there but
        wrong, so a code Marmin doesn't accept still throws instead of
        being sent anyway and bouncing back as another opaque 400."""
        entries = []

        for pay_row in (doc.payments or []):
            if not pay_row.mode_of_payment:
                continue

            mop = frappe.get_doc("Mode of Payment", pay_row.mode_of_payment)
            pm_code = mop.get("custom_payment_means_codes") or ""
            if " - " not in pm_code:
                continue

            payment_code, _sep, _name = pm_code.partition(" - ")
            payment_code = payment_code.strip()

            if payment_code not in MARMIN_APPROVED_PAYMENT_MEANS_CODES:
                frappe.throw(
                    _(
                        "Mode of Payment {0}'s payment means code '{1}' isn't one "
                        "Marmin accepts ({2}). Update its Payment Means Code to a "
                        "supported one."
                    ).format(
                        mop.name,
                        payment_code,
                        ", ".join(sorted(MARMIN_APPROVED_PAYMENT_MEANS_CODES)),
                    )
                )

            entry = {"payment_means_code": payment_code}

            if payment_code == "30":
                if not mop.accounts:
                    frappe.throw(
                        _(
                            "Mode of Payment {0} needs a bank Account under its "
                            "Accounts table - Marmin requires payee_financial_account "
                            "for payment means code 30."
                        ).format(mop.name)
                    )
                acc = frappe.get_doc("Account", mop.accounts[0].default_account)
                entry["payee_financial_account"] = {
                    "id": acc.account_number,
                    "name": acc.account_name,
                }
            elif payment_code in ("54", "55", "49"):
                # card_account (54/55) and payment_mandate (49) aren't wired
                # up - no real card/mandate data exists on this invoice to
                # send, and sending fake placeholder values isn't better than
                # a clear error telling you this combination isn't supported
                # yet.
                frappe.throw(
                    _(
                        "Mode of Payment {0} uses payment means code {1}, which needs "
                        "card_account or payment_mandate details this adapter doesn't "
                        "build yet - use a bank transfer (30) or cash (10) Mode of "
                        "Payment instead, or ask to have this one filled in."
                    ).format(mop.name, payment_code)
                )

            entries.append(entry)

        if not entries:
            entries = [{"payment_means_code": MARMIN_DEFAULT_PAYMENT_MEANS_CODE}]

        return entries

    def _build_accounting_supplier_party(self, doc):
        """Seller party block, built from the Company doctype - this was
        missing entirely before, which is exactly why Marmin's 400 said
        accounting_supplier_party and accounting_customer_party "cannot be
        the same entity" (with nothing sent for the supplier side, Marmin
        had nothing to tell it apart from the buyer).

        NOTE: an earlier version of this mirrored Flick's own
        update_participant() (providers/flick/adapter.py), reading
        company_doc.custom_peppol_id / custom_street_address / etc. That
        crashed with AttributeError - Company has NO such fields at all
        (confirmed against fixtures/custom_field.json: Company only carries
        the 5 e-invoicing toggle fields), so update_participant() was
        apparently always dead code, never actually invoked (nothing in the
        app calls it except an unused wrapper in participant.py).

        So this now uses only real data: endpoint_id is this row's own
        Participant ID (the Business Profile ID Marmin already knows this
        company by - same field submit_invoice() already uses for the URL),
        and the postal address/contact details come from the Company's
        actual linked Address record, via frappe's core get_default_address()
        - the same Address doctype and same fields (address_line1,
        emirate, email_id, phone, ...) the buyer side below already reads
        successfully, since Company doesn't have inline address fields any
        more than Customer does."""
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

        country_subentity = get_uae_emirate_code(address_data.emirate)
        if country_code == "AE" and not country_subentity:
            frappe.throw(
                _(
                    "Company {0}'s address needs a recognised UAE emirate "
                    "(Abu Dhabi, Dubai, Sharjah, Ajman, Umm Al Quwain, Ras Al "
                    "Khaimah or Fujairah) - Marmin requires this for the "
                    "supplier's postal address."
                ).format(company_doc.name)
            )

        # Marmin's schema notes call telephone mandatory specifically for
        # UAE suppliers (unlike the buyer side, where it's not required).
        if country_code == "AE" and not address_data.phone:
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
            # profile_id: Marmin's own internal Business Profile reference
            # for this party (separate from endpoint_id, which is the
            # PEPPOL network identifier) - same value already used for the
            # submit URL and as endpoint_id above, since that IS this
            # company's Business Profile ID. Not set on the buyer side
            # (_build_accounting_customer_party) - we don't have a Marmin
            # profile_id for an external buyer, only their PEPPOL endpoint
            # id, and there's no confirmed docs page yet saying that's
            # required for a non-Marmin-registered buyer.
            "profile_id": self.settings.participant_id,
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

        # tax_id is Company's standard "Tax ID" field (not a custom_* one) -
        # same TRN value doubling as Marmin's "tin" and party_tax_scheme.
        if company_doc.tax_id:
            party["tin"] = company_doc.tax_id
            party["party_tax_scheme"] = {
                "company_id": company_doc.tax_id,
                "tax_scheme": "VAT",
            }

        return party

    def _build_accounting_customer_party(self, doc):
        """Buyer party block, built from the same Customer + Address fields
        Flick's own PEPPOL builder already reads (build_uae_invoice_json in
        json_einvoice.py) - custom_peppol_id as the buyer's endpoint id,
        tax_id as its VAT number, and the customer's primary/invoice address
        for postal_address. Marmin just wants all of it nested under
        accounting_customer_party instead of flat."""
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

        country_subentity = get_uae_emirate_code(address_data.emirate)
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

        # tax_id doubles as both the "VAT identifier" alternative Marmin
        # accepts instead of a buyer identifier on non-export invoices, and
        # the party_tax_scheme.company_id their schema separately asks for -
        # same single field Flick's builder already uses as vat_number.
        if customer_doc.tax_id:
            party["tin"] = customer_doc.tax_id
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
        get_vat_category_code() - so both providers agree on what "standard
        rated", "zero rated", etc. mean for this company, instead of Marmin
        inventing its own second mapping. Same for the exemption reason
        (custom_vat_exemption_reason_code) Marmin requires whenever the
        category comes out "E" (exempt)."""
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

        vat_code = get_vat_category_code(vat_category) if vat_category else "S"

        classified_tax_category = {
            "id": vat_code,
            "percent": float(tax_rate or 0),
            "tax_scheme": "VAT",
        }

        if vat_code == "E":
            # Marmin requires both a code and a description here whenever the
            # category is Exempt - custom_vat_exemption_reason_code stores
            # something like "VATEX-AE-32-1 - Public postal services", so
            # split on the first " - " to get code vs. description the same
            # way the Flick/PEPPOL builder already does for its own field.
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