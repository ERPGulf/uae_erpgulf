# # """Marmin AI Software Design LLC adapter.

# # Built from two sources: the one docs page we've seen
# # (https://docs.ae.marmin.ai/docs/2026-05-07/flow/businesses/sale-documents/sale-invoices/create,
# # covering ONLY "create a sale invoice"), and a follow-up email from Marmin
# # with sandbox config: Client ID, Client Secret, Business Profile ID, API
# # Version, Base URL, and a Token Endpoint (GET .../auth/token). Put the
# # Client ID/Client Secret/Business Profile ID (as Participant ID)/Base URL
# # from that email onto the company's E-Invoice Provider Settings row -
# # that's what this adapter reads.

# # Everything below other than auth and submit_invoice still has no verified
# # docs page, so it raises a clear error explaining exactly what's missing
# # instead of guessing a URL or payload shape. Fill each one in - and delete
# # its "not implemented yet" throw - once you have the matching docs page
# # for it, the same way submit_invoice and _fetch_token were filled in below.

# # The exact token flow (confirmed by Marmin, not guessed): HMAC-SHA256-sign
# # the Client ID using the Client Secret as the key, base64-encode that
# # signature, then GET /auth/token?client_id=<CLIENT_ID> with that signature
# # in an x-marmin-signature header. That's what _fetch_token does below.
# # """

# # import base64
# # import hmac
# # import hashlib

# # import frappe
# # import requests
# # from frappe import _

# # from uae_erpgulf.uae_erpgulf.providers.base import BaseAdapter

# # MARMIN_API_VERSION = "20260507"  # from the 2026-05-07 docs page
# # MARMIN_INVOICE_TYPE_CODE_STANDARD = "380"  # standard invoice, per Marmin's docs (380 or 480)


# # class MarminAdapter(BaseAdapter):

# #     # ---- auth ----
# #     def get_auth_headers(self, extra=None):
# #         headers = dict(extra or {})
# #         headers["Authorization"] = f"Bearer {self.get_valid_token()}"
# #         headers["X-MARMIN-VERSION"] = MARMIN_API_VERSION
# #         return headers

# #     def _fetch_token(self):
# #         settings = self.settings
# #         base_url = self.get_base_url()
# #         client_id = settings.client_id
# #         client_secret = settings.get_password("client_secret")

# #         if not base_url or not client_id or not client_secret:
# #             frappe.throw(
# #                 _("Please enter Base URL, Client ID and Client Secret on E-Invoice Provider Settings.")
# #             )

# #         # HMAC-SHA256(key=client_secret, message=client_id), base64-encoded -
# #         # exactly the signature Marmin's token endpoint expects in
# #         # x-marmin-signature.
# #         signature = base64.b64encode(
# #             hmac.new(
# #                 client_secret.encode("utf-8"),
# #                 client_id.encode("utf-8"),
# #                 hashlib.sha256,
# #             ).digest()
# #         ).decode("utf-8")

# #         url = f"{base_url}/auth/token"
# #         headers = {
# #             "x-marmin-signature": signature,
# #             "X-MARMIN-VERSION": MARMIN_API_VERSION,
# #         }

# #         response = requests.get(url, params={"client_id": client_id}, headers=headers)

# #         if not response.ok:
# #             frappe.throw(
# #                 _("Marmin token request failed ({0}): {1}").format(
# #                     response.status_code, response.text
# #                 )
# #             )

# #         try:
# #             response_json = response.json()
# #         except Exception:
# #             frappe.throw(_("Marmin token response wasn't JSON: {0}").format(response.text))

# #         access_token = (
# #             response_json.get("access_token")
# #             or response_json.get("token")
# #             or response_json.get("data", {}).get("access_token")
# #         )

# #         if not access_token:
# #             frappe.throw(
# #                 _("Access token not found in Marmin token response: {0}").format(response_json)
# #             )

# #         self.set_cached_token(access_token)
# #         return access_token

# #     # ---- not yet backed by a verified docs page ----
# #     def verify_auth(self):
# #         frappe.throw(_("Marmin auth verification isn't implemented yet - no docs page for it."))

# #     def get_participant_details(self):
# #         frappe.throw(_("Marmin participant lookup isn't implemented yet - no docs page for it."))

# #     def lookup_peppol_id(self, peppol_id):
# #         frappe.throw(_("Marmin PEPPOL lookup isn't implemented yet - no docs page for it."))

# #     def update_participant(self, company_doc):
# #         frappe.throw(_("Marmin participant update isn't implemented yet - no docs page for it."))

# #     def get_document_status(self, doctype, doc):
# #         frappe.throw(_("Marmin status-check isn't implemented yet - no docs page for it."))

# #     def get_document_xml(self, doctype, doc):
# #         frappe.throw(_("Marmin doesn't have a documented XML endpoint yet."))

# #     def get_document_pdf(self, doctype, doc):
# #         frappe.throw(_("Marmin doesn't have a documented PDF endpoint yet."))

# #     def register_webhook(self):
# #         frappe.throw(_("Marmin webhook registration isn't implemented yet - no docs page for it."))

# #     def get_subscription(self):
# #         frappe.throw(_("Marmin webhook subscription isn't implemented yet - no docs page for it."))

# #     def get_webhook_deliveries(self):
# #         frappe.throw(_("Marmin webhook deliveries isn't implemented yet - no docs page for it."))

# #     # ---- invoices: the one thing we do have real docs for ----
# #     def submit_invoice(self, doctype, doc, json_data):
# #         """POST /api/sales-invoices/{business_profile_id}

# #         NOTE: Sales Invoice only for now - the docs page we have is
# #         specifically "sale-invoices/create". Purchase Invoice needs its own
# #         Marmin docs page before this can support it.
# #         """
# #         if doctype != "Sales Invoice":
# #             frappe.throw(_("Marmin adapter only supports Sales Invoice submission so far."))

# #         settings = self.settings
# #         business_profile_id = settings.participant_id
# #         if not business_profile_id:
# #             frappe.throw(
# #                 _(
# #                     "Business Profile ID (stored in Participant ID) is missing on "
# #                     "E-Invoice Provider Settings"
# #                 )
# #             )

# #         base_url = self.get_base_url()
# #         url = f"{base_url}/api/sales-invoices/{business_profile_id}"
# #         headers = self.get_auth_headers({"Content-Type": "application/json"})

# #         payload = self._build_invoice_payload(doc)

# #         response = requests.post(url, headers=headers, json=payload, timeout=120)

# #         try:
# #             response_data = response.json()
# #         except Exception:
# #             response_data = response.text

# #         return response.status_code, response_data

# #     def _build_invoice_payload(self, doc):
# #         """Maps a Sales Invoice to Marmin's flat JSON shape. Only the fields
# #         we're confident about are filled in here - Marmin's docs list 30+
# #         further optional fields (delivery info, payment means, allowances,
# #         etc.) that aren't mapped yet. Extend this once you've confirmed the
# #         matching field names on your own Sales Invoice doctype and want to
# #         send more than the minimum required fields.

# #         NOTE: this builds straight from the Sales Invoice document (doc),
# #         not from json_data - json_data is the PEPPOL/UBL-style JSON built for
# #         Flick, and Marmin's payload shape is a different, flat JSON, so
# #         json_data isn't reused here (it's still accepted as a parameter to
# #         match the shared submit_invoice interface every adapter uses).
# #         """
# #         return {
# #             "profile_execution_id": self.settings.name,
# #             "issue_date": str(doc.posting_date),
# #             "invoice_type_code": MARMIN_INVOICE_TYPE_CODE_STANDARD,
# #             "due_date": str(doc.due_date) if doc.due_date else str(doc.posting_date),
# #             "document_currency_code": doc.currency,
# #             "accounting_customer_party": {
# #                 "name": doc.customer_name,
# #             },
# #             "document_lines": [
# #                 {
# #                     "item_name": item.item_name,
# #                     "quantity": item.qty,
# #                     "unit_price": item.rate,
# #                     "line_amount": item.amount,
# #                 }
# #                 for item in doc.items
# #             ],
# #         }
# """Marmin AI Software Design LLC adapter.

# Built from two sources: the one docs page we've seen
# (https://docs.ae.marmin.ai/docs/2026-05-07/flow/businesses/sale-documents/sale-invoices/create,
# covering ONLY "create a sale invoice"), and a follow-up email from Marmin
# with sandbox config: Client ID, Client Secret, Business Profile ID, API
# Version, Base URL, and a Token Endpoint (GET .../auth/token). Put the
# Client ID/Client Secret/Business Profile ID (as Participant ID)/Base URL
# from that email onto the company's E-Invoice Provider Settings row -
# that's what this adapter reads.

# Everything below other than auth, submit_invoice and get_participant_details
# still has no verified docs page, so it raises a clear error explaining
# exactly what's missing instead of guessing a URL or payload shape. Fill
# each one in - and delete its "not implemented yet" throw - once you have
# the matching docs page for it, the same way those three were filled in.

# Note on get_participant_details specifically: Marmin has no "participant"
# concept at all - their docs are organized around "Business Profiles"
# instead (Party Management > Business Profiles > Retrieve a Business
# Profile, GET /api/business-profiles/{profileId}). It's the same underlying
# idea (a registered legal entity + its PEPPOL endpoint), just named
# differently, which is exactly why the doctype field for it is called the
# provider-neutral "Participant ID" rather than something Flick-specific -
# every adapter reads/writes that same field, under whatever name its own
# ASP calls it.

# The exact token flow (confirmed by Marmin, not guessed): HMAC-SHA256-sign
# the Client ID using the Client Secret as the key, base64-encode that
# signature, then GET /auth/token?client_id=<CLIENT_ID> with that signature
# in an x-marmin-signature header. That's what _fetch_token does below.
# """

# import base64
# import hmac
# import hashlib

# import frappe
# import requests
# from frappe import _

# from uae_erpgulf.uae_erpgulf.providers.base import BaseAdapter

# MARMIN_API_VERSION = "20260507"  # from the 2026-05-07 docs page
# MARMIN_INVOICE_TYPE_CODE_STANDARD = "380"  # standard invoice, per Marmin's docs (380 or 480)


# class MarminAdapter(BaseAdapter):

#     # ---- auth ----
#     def get_auth_headers(self, extra=None):
#         headers = dict(extra or {})
#         headers["Authorization"] = f"Bearer {self.get_valid_token()}"
#         headers["X-MARMIN-VERSION"] = MARMIN_API_VERSION
#         return headers

#     def _fetch_token(self):
#         settings = self.settings
#         base_url = self.get_base_url()
#         client_id = settings.client_id
#         client_secret = settings.get_password("client_secret")

#         if not base_url or not client_id or not client_secret:
#             frappe.throw(
#                 _("Please enter Base URL, Client ID and Client Secret on E-Invoice Provider Settings.")
#             )

#         # HMAC-SHA256(key=client_secret, message=client_id), base64-encoded -
#         # exactly the signature Marmin's token endpoint expects in
#         # x-marmin-signature.
#         signature = base64.b64encode(
#             hmac.new(
#                 client_secret.encode("utf-8"),
#                 client_id.encode("utf-8"),
#                 hashlib.sha256,
#             ).digest()
#         ).decode("utf-8")

#         url = f"{base_url}/auth/token"
#         headers = {
#             "x-marmin-signature": signature,
#             "X-MARMIN-VERSION": MARMIN_API_VERSION,
#         }

#         response = requests.get(url, params={"client_id": client_id}, headers=headers)

#         if not response.ok:
#             frappe.throw(
#                 _("Marmin token request failed ({0}): {1}").format(
#                     response.status_code, response.text
#                 )
#             )

#         try:
#             response_json = response.json()
#         except Exception:
#             frappe.throw(_("Marmin token response wasn't JSON: {0}").format(response.text))

#         access_token = (
#             response_json.get("access_token")
#             or response_json.get("token")
#             or response_json.get("data", {}).get("access_token")
#         )

#         if not access_token:
#             frappe.throw(
#                 _("Access token not found in Marmin token response: {0}").format(response_json)
#             )

#         self.set_cached_token(access_token)
#         return access_token

#     # ---- not yet backed by a verified docs page ----
#     def verify_auth(self):
#         frappe.throw(_("Marmin auth verification isn't implemented yet - no docs page for it."))

#     def get_participant_details(self):
#         """GET /api/business-profiles/{profileId}

#         Marmin doesn't have a separate "participant" concept the way Flick
#         does - a Business Profile IS the registered party/PEPPOL endpoint,
#         confirmed from their Party Management > Business Profiles docs page.
#         So this reads the same ID already stored in Participant ID (reused
#         as business_profile_id everywhere else in this adapter too)."""
#         settings = self.settings
#         business_profile_id = settings.participant_id
#         if not business_profile_id:
#             frappe.throw(
#                 _(
#                     "Business Profile ID (stored in Participant ID) is missing on "
#                     "E-Invoice Provider Settings"
#                 )
#             )

#         base_url = self.get_base_url()
#         url = f"{base_url}/api/business-profiles/{business_profile_id}"
#         headers = self.get_auth_headers()

#         response = requests.get(url, headers=headers)
#         if response.status_code == 200:
#             return {"status": "success", "response": response.json()}

#         frappe.throw(_("Marmin API Error: {0}").format(response.text))

#     def lookup_peppol_id(self, peppol_id):
#         frappe.throw(_("Marmin PEPPOL lookup isn't implemented yet - no docs page for it."))

#     def update_participant(self, company_doc):
#         frappe.throw(_("Marmin participant update isn't implemented yet - no docs page for it."))

#     def get_document_status(self, doctype, doc):
#         frappe.throw(_("Marmin status-check isn't implemented yet - no docs page for it."))

#     def get_document_xml(self, doctype, doc):
#         frappe.throw(_("Marmin doesn't have a documented XML endpoint yet."))

#     def get_document_pdf(self, doctype, doc):
#         frappe.throw(_("Marmin doesn't have a documented PDF endpoint yet."))

#     def register_webhook(self):
#         frappe.throw(_("Marmin webhook registration isn't implemented yet - no docs page for it."))

#     def get_subscription(self):
#         frappe.throw(_("Marmin webhook subscription isn't implemented yet - no docs page for it."))

#     def get_webhook_deliveries(self):
#         frappe.throw(_("Marmin webhook deliveries isn't implemented yet - no docs page for it."))

#     # ---- invoices: the one thing we do have real docs for ----
#     def submit_invoice(self, doctype, doc, json_data):
#         """POST /api/sales-invoices/{business_profile_id}

#         NOTE: Sales Invoice only for now - the docs page we have is
#         specifically "sale-invoices/create". Purchase Invoice needs its own
#         Marmin docs page before this can support it.
#         """
#         if doctype != "Sales Invoice":
#             frappe.throw(_("Marmin adapter only supports Sales Invoice submission so far."))

#         settings = self.settings
#         business_profile_id = settings.participant_id
#         if not business_profile_id:
#             frappe.throw(
#                 _(
#                     "Business Profile ID (stored in Participant ID) is missing on "
#                     "E-Invoice Provider Settings"
#                 )
#             )

#         base_url = self.get_base_url()
#         url = f"{base_url}/api/sales-invoices/{business_profile_id}"
#         headers = self.get_auth_headers({"Content-Type": "application/json"})

#         payload = self._build_invoice_payload(doc)

#         response = requests.post(url, headers=headers, json=payload, timeout=120)

#         try:
#             response_data = response.json()
#         except Exception:
#             response_data = response.text

#         return response.status_code, response_data

#     def _build_invoice_payload(self, doc):
#         """Maps a Sales Invoice to Marmin's flat JSON shape. Only the fields
#         we're confident about are filled in here - Marmin's docs list 30+
#         further optional fields (delivery info, payment means, allowances,
#         etc.) that aren't mapped yet. Extend this once you've confirmed the
#         matching field names on your own Sales Invoice doctype and want to
#         send more than the minimum required fields.

#         NOTE: this builds straight from the Sales Invoice document (doc),
#         not from json_data - json_data is the PEPPOL/UBL-style JSON built for
#         Flick, and Marmin's payload shape is a different, flat JSON, so
#         json_data isn't reused here (it's still accepted as a parameter to
#         match the shared submit_invoice interface every adapter uses).
#         """
#         return {
#             "profile_execution_id": self.settings.name,
#             "issue_date": str(doc.posting_date),
#             "invoice_type_code": MARMIN_INVOICE_TYPE_CODE_STANDARD,
#             "due_date": str(doc.due_date) if doc.due_date else str(doc.posting_date),
#             "document_currency_code": doc.currency,
#             "accounting_customer_party": {
#                 "name": doc.customer_name,
#             },
#             "document_lines": [
#                 {
#                     "item_name": item.item_name,
#                     "quantity": item.qty,
#                     "unit_price": item.rate,
#                     "line_amount": item.amount,
#                 }
#                 for item in doc.items
#             ],
#         }
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

import frappe
import requests
from frappe import _

from uae_erpgulf.uae_erpgulf.providers.base import BaseAdapter

MARMIN_API_VERSION = "20260507"  # from the 2026-05-07 docs page
MARMIN_INVOICE_TYPE_CODE_STANDARD = "380"  # standard invoice, per Marmin's docs (380 or 480)


class MarminAdapter(BaseAdapter):

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
        frappe.throw(_("Marmin status-check isn't implemented yet - no docs page for it."))

    def get_document_xml(self, doctype, doc):
        frappe.throw(_("Marmin doesn't have a documented XML endpoint yet."))

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

        response = requests.post(url, headers=headers, json=payload, timeout=120)

        try:
            response_data = response.json()
        except Exception:
            response_data = response.text

        return response.status_code, response_data

    def _build_invoice_payload(self, doc):
        """Maps a Sales Invoice to Marmin's flat JSON shape. Only the fields
        we're confident about are filled in here - Marmin's docs list 30+
        further optional fields (delivery info, payment means, allowances,
        etc.) that aren't mapped yet. Extend this once you've confirmed the
        matching field names on your own Sales Invoice doctype and want to
        send more than the minimum required fields.

        NOTE: this builds straight from the Sales Invoice document (doc),
        not from json_data - json_data is the PEPPOL/UBL-style JSON built for
        Flick, and Marmin's payload shape is a different, flat JSON, so
        json_data isn't reused here (it's still accepted as a parameter to
        match the shared submit_invoice interface every adapter uses).
        """
        return {
            "profile_execution_id": self.settings.name,
            "issue_date": str(doc.posting_date),
            "invoice_type_code": MARMIN_INVOICE_TYPE_CODE_STANDARD,
            "due_date": str(doc.due_date) if doc.due_date else str(doc.posting_date),
            "document_currency_code": doc.currency,
            "accounting_customer_party": {
                "name": doc.customer_name,
            },
            "document_lines": [
                {
                    "item_name": item.item_name,
                    "quantity": item.qty,
                    "unit_price": item.rate,
                    "line_amount": item.amount,
                }
                for item in doc.items
            ],
        }