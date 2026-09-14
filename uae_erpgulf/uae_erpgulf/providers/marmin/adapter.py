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
# import json

# import frappe
# import requests
# from frappe import _

# from uae_erpgulf.uae_erpgulf.providers.base import BaseAdapter
# from uae_erpgulf.uae_erpgulf.json_einvoice import (
#     get_vat_category_code,
#     get_uae_emirate_code,
#     get_invoice_type_code,
#     get_payment_means,
#     get_issue_time,
# )
# from uae_erpgulf.uae_erpgulf.country_code import country_code_mapping

# MARMIN_API_VERSION = "20260507"  # from the 2026-05-07 docs page

# # profile_execution_id is NOT a docname or any kind of ID we generate - it's an
# # 8-digit flag string (each digit 0 or 1) from Marmin's docs, one position per
# # special scenario (FTZ, deemed supply, profit margin scheme, summary invoice,
# # continuous supply, disclosed agent billing, e-commerce supply, exports).
# # "00000000" means none of those apply - a normal invoice, which is the only
# # case this adapter builds so far. If you need one of those scenarios, flip
# # the matching digit rather than adding a new constant.
# MARMIN_PROFILE_EXECUTION_ID_STANDARD = "00000000"

# # payment_means is mandatory and Marmin only accepts these codes: 1, 10, 20,
# # 21, 30, 49, 54, 55, 68 - a different (mostly overlapping) list from the one
# # Flick/PEPPOL's own get_payment_means() checks against (which also allows
# # 48/57/58), so a Mode of Payment set up only for Flick may not carry a code
# # Marmin accepts. This is a real constraint from Marmin's own docs, not a
# # guessed value.
# #
# # "1" (UNCL4461 "Instrument not defined") is used as a LAST-RESORT fallback
# # only - confirmed necessary the hard way: an invoice with no real payment
# # data sent an empty payment_means array and Marmin rejected the whole
# # submission with a 400 ("At least one payment means is mandatory"), since
# # it's a mandatory field with no concept of "not applicable". So
# # _build_payment_means below always tries get_payment_means(doc) (Flick's
# # own real Payments-table derivation) FIRST, and only reaches for this
# # static code when that comes back completely empty - real data from the
# # invoice always wins over this default when it's actually there.
# MARMIN_DEFAULT_PAYMENT_MEANS_CODE = "1"
# MARMIN_APPROVED_PAYMENT_MEANS_CODES = {"1", "10", "20", "21", "30", "49", "54", "55", "68"}

# # PEPPOL endpoint scheme id - Marmin's docs say "typically 0235 for UAE",
# # same network Flick's custom_peppol_id values already come from.
# MARMIN_ENDPOINT_SCHEME_ID_UAE = "0235"

# # unit_code must be a UN/ECE Rec 20/21 code (EA, KGM, LTR, ...), not ERPNext's
# # own UOM name - this maps the common ones and falls back to "EA" (each) for
# # anything unmapped. Extend this if you sell in units it doesn't cover yet.
# MARMIN_UOM_TO_UNECE_CODE = {
#     "nos": "EA", "unit": "EA", "each": "EA", "pcs": "EA", "piece": "EA",
#     "kg": "KGM", "kilogram": "KGM",
#     "gram": "GRM", "gm": "GRM",
#     "litre": "LTR", "liter": "LTR", "ltr": "LTR",
#     "meter": "MTR", "metre": "MTR", "mtr": "MTR",
#     "box": "BX",
#     "pair": "PR",
#     "dozen": "DZN",
#     "hour": "HUR",
#     "day": "DAY",
# }


# class MarminAdapter(BaseAdapter):
#     # Marmin's payload is built straight from the Sales Invoice doc
#     # (_build_invoice_payload below), never from the shared
#     # "<invoice>_uae_invoice.json" file - so there's no reason to generate
#     # or attach that Flick-shaped file for a Marmin-configured company at
#     # all. See USES_SHARED_INVOICE_JSON on BaseAdapter.
#     USES_SHARED_INVOICE_JSON = False

#     # Marmin's XML (and possibly PDF - same async document pipeline) is
#     # generated some time after an invoice is accepted, so a "not generated
#     # yet" response right after submit is normal, not a bug. This used to be
#     # False specifically because PDF had no documented endpoint at all -
#     # now that both get_document_xml and get_document_pdf are implemented
#     # (see below), it's back to the base class default (True): test.py's
#     # generate_and_send_einvoice tries both automatically right after a
#     # successful submit, exactly like it always has for Flick. If Marmin
#     # hasn't actually finished generating one yet, that attempt now just
#     # gets logged quietly (see the fix in test.py/attach.py that shows the
#     # real reason instead of a scary generic error) rather than disrupting
#     # the submit - so trying automatically costs nothing on a "not ready"
#     # response, and saves a manual click whenever Marmin happens to be
#     # ready immediately. The "Get Document XML"/"Get Document PDF" buttons
#     # in sales_invoice.js are still there as a manual fallback/retry.

#     # Marmin's own generation delay is exactly the case
#     # DOCUMENT_FETCH_RETRY_ATTEMPTS/DELAY_SECONDS (providers/base.py) exist
#     # for - give the immediate-after-submit auto-fetch a few short-spaced
#     # tries before falling back to "log it and let the manual buttons
#     # handle it later". NOT a confirmed number from Marmin's docs (no docs
#     # page states a generation SLA) - 3 tries, 5 seconds apart (~10s worst
#     # case added to a submit that would otherwise fail this step anyway) is
#     # a starting guess, tune it if documents still aren't ready by then or
#     # if this is adding more delay than you want on every submission.
#     DOCUMENT_FETCH_RETRY_ATTEMPTS = 3
#     DOCUMENT_FETCH_RETRY_DELAY_SECONDS = 5

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

#         # expires_in isn't confirmed in any Marmin docs page we've seen - this
#         # is a best-effort read of the same field name OAuth2-style responses
#         # commonly use, in case Marmin's token endpoint includes it. Falls
#         # back to the base class's default (55 minutes) when it's absent, so
#         # nothing changes for the common case where Marmin doesn't send it.
#         expires_in = response_json.get("expires_in") or response_json.get("data", {}).get(
#             "expires_in"
#         )
#         if isinstance(expires_in, (int, float)) and expires_in > 0:
#             self.set_cached_token(access_token, expires_in_sec=int(expires_in))
#         else:
#             self.set_cached_token(access_token)

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

#     def _document_resource_path(self, doc):
#         """"sales-invoices" or "sales-credit-notes" - which of Marmin's two
#         resource collections this document's own Marmin id (the "id" saved
#         in custom_submit_response) actually lives under.

#         Confirmed for the submit side only: invoices go to
#         POST /api/sales-invoices/{business_profile_id}, credit notes to
#         POST /api/sales-credit-notes/{business_profile_id} (real curl
#         example from Marmin's docs). This method extends that same
#         substitution to the READ side (peppol-status-logs/xml/download-pdf)
#         by inference, not a separately confirmed docs page for each - a
#         credit note's status/xml/pdf 200-ing with an empty/wrong result
#         under sales-invoices/{id} (rather than a 404) is exactly what you'd
#         see if that id only exists under sales-credit-notes instead, which
#         is the whole reason this exists. If a read-side call ever comes
#         back wrong even after using the right resource path here, that's
#         the next thing to check against Marmin's own docs for that specific
#         endpoint."""
#         return "sales-credit-notes" if doc.is_return else "sales-invoices"

#     def get_document_status(self, doctype, doc):
#         """GET /api/sales-invoices/{id}/peppol-status-logs - confirmed docs
#         page (sandbox example: curl .../api/sales-invoices/{id}/peppol-status-logs
#         -H "Authorization: Bearer <token>"). Response is JSON - a log of this
#         document's PEPPOL exchange/reporting status entries, which is exactly
#         what the "Get Document Status" button (already in the UI, wired to
#         the generic get_document_status in verify_token.py) is for: click it
#         later, once Marmin has actually finished processing the document,
#         instead of this adapter guessing at a status right after submit.

#         {id} is MARMIN's OWN invoice id, same as get_document_xml above - read
#         out of the saved submit response, not doc.name/Business Profile ID.

#         Marmin's docs example for this one only shows an Authorization
#         header, not X-MARMIN-VERSION (unlike every other endpoint we've
#         confirmed for them) - still sending it anyway via get_auth_headers()
#         for consistency, since nothing in the docs says an extra header here
#         is rejected. If this endpoint ever 400s specifically because of that
#         header, that's the first thing to try removing.

#         Return shape: always {"http_status": <int>, "response": <body>},
#         success or failure - this used to frappe.throw() on a non-200
#         instead of returning, which meant a failure here escaped as Frappe's
#         own generic red error dialog (no HTTP status, no real detail) rather
#         than the "Get Document Status" button's own dialog in
#         sales_invoice.js. Returning the status code alongside the body lets
#         that dialog show both, and decide its own colour instead of Frappe
#         picking one for it."""
#         if not doc.custom_submit_response:
#             frappe.throw(_("Submit response not found in Invoice"))

#         response_data = json.loads(doc.custom_submit_response)
#         document_id = response_data.get("id") or response_data.get("data", {}).get("id")
#         if not document_id:
#             frappe.throw(_("Marmin invoice id not found in submit response"))

#         base_url = self.get_base_url()
#         resource = self._document_resource_path(doc)
#         url = f"{base_url}/api/{resource}/{document_id}/peppol-status-logs"
#         headers = self.get_auth_headers()

#         response = requests.get(url, headers=headers)
#         try:
#             body = response.json()
#         except Exception:
#             body = response.text

#         result = {"http_status": response.status_code, "response": body}

#         # Unlike Flick, whose response has a flat reporting_status field,
#         # Marmin's peppol-status-logs response is a plain chronological log
#         # ({event, message, timestamp} entries) with no status field at
#         # all - so derive one, the same "reported"/"pending"/"failed"/"not
#         # reported" vocabulary badge_sales.js already keys the FTA badge
#         # off of (custom_reporting_status), so the badge works for Marmin
#         # invoices too instead of never getting set. Only meaningful when
#         # the response actually is that list shape - a non-200 error body,
#         # or some other shape, leaves this key out entirely.
#         if isinstance(body, list):
#             derived = self._reporting_status_from_status_logs(body)
#             if derived:
#                 result["reporting_status"] = derived

#         return result

#     @staticmethod
#     def _reporting_status_from_status_logs(events):
#         """Best-effort derivation of a reporting_status from Marmin's
#         peppol-status-logs event list. This list uses UAE PEPPOL 5-corner
#         terminology: C2 is this document's own sending access point (i.e.
#         Marmin itself here), C3 is the buyer's access point, and C5 is the
#         FTA - the UAE model's own "5th corner" tax authority node. MLS
#         means Message Level Status, PEPPOL's standard delivery-receipt
#         concept.

#         ONLY the "reported" branch below is confirmed, against one real,
#         fully-successful invoice's log: its last two entries were both
#         event "MLS_RECEIVED_FROM_C5", the final one with message "Received
#         MLS from C5 with AP response. Marked the document as sent" - i.e.
#         Marmin's own signal that the FTA has acknowledged the document.

#         The "failed"/"pending"/"not reported" branches are a reasonable
#         heuristic built from that same vocabulary (an event name so far
#         always describes what happened using "_TO_C5"/"_FROM_C5"/etc.),
#         NOT confirmed against a real failed or pending example, or any
#         Marmin docs page listing every possible event/message - there's no
#         docs page for this endpoint's response shape at all, only the
#         sandbox curl example showing the request. If a real failure or
#         pending case ever comes through and lands in the wrong bucket
#         here, share that log's exact events/messages and this can be
#         tightened against real evidence instead of guesswork."""
#         if not isinstance(events, list) or not events:
#             return None

#         # Sort defensively by timestamp - "the latest state" only means
#         # something if this is genuinely chronological, and nothing
#         # guarantees the ASP always returns it already sorted.
#         try:
#             events = sorted(events, key=lambda e: e.get("timestamp") or 0)
#         except Exception:
#             pass

#         haystack = " ".join(
#             f"{e.get('event') or ''} {e.get('message') or ''}"
#             for e in events
#             if isinstance(e, dict)
#         ).lower()

#         if any(k in haystack for k in ("fail", "reject", "error", "invalid")):
#             return "failed"

#         # Confirmed case: the FTA (C5) sent back a Message Level Status.
#         if "mls_received_from_c5" in haystack or "received mls from c5" in haystack:
#             return "reported"

#         # Heuristic: queued to or transmitted toward the FTA (C5), but no
#         # MLS response back from it yet - still in flight.
#         if "to_c5" in haystack or "to c5" in haystack:
#             return "pending"

#         # Heuristic: nothing in this log even mentions C5 (the FTA) yet.
#         return "not reported"

#     def get_document_xml(self, doctype, doc):
#         """GET /api/sales-invoices/{id}/xml - confirmed docs page (sandbox
#         example: curl .../api/sales-invoices/{id}/xml -H "Authorization:
#         Bearer <token>" -H "X-MARMIN-VERSION: ..." -o invoice.xml). Response
#         is raw XML text, not JSON - unlike get_participant_details above.

#         {id} here is MARMIN's OWN invoice id - a UUID it assigns once the
#         invoice is accepted (not this Sales Invoice's own name/
#         document_number, and not the Business Profile ID either) - so it
#         has to be read back out of the saved submit response rather than
#         off doc directly. Checked at the top level first (response_data["id"]
#         - matches the shape of Marmin's fuller invoice-object reference
#         example, where "id" sits at the top, not nested), falling back to
#         a Flick-style nested ["data"]["id"] in case Marmin's real response
#         turns out to nest it after all."""
#         if not doc.custom_submit_response:
#             frappe.throw(_("Submit response not found in Invoice"))

#         response_data = json.loads(doc.custom_submit_response)
#         document_id = response_data.get("id") or response_data.get("data", {}).get("id")
#         if not document_id:
#             frappe.throw(_("Marmin invoice id not found in submit response"))

#         base_url = self.get_base_url()
#         resource = self._document_resource_path(doc)
#         url = f"{base_url}/api/{resource}/{document_id}/xml"
#         headers = self.get_auth_headers()

#         response = requests.get(url, headers=headers)
#         if response.status_code == 200:
#             return response.text

#         frappe.throw(_("Marmin API Error: {0}").format(response.text))

#     def get_document_pdf(self, doctype, doc):
#         """GET /api/sales-invoices/{id}/download-pdf - confirmed docs
#         example (sandbox: curl .../api/sales-invoices/{id}/download-pdf -H
#         "Authorization: Bearer <token>"). Note the path is "download-pdf",
#         not just "/pdf" the way Flick's own PDF endpoint is shaped - don't
#         assume the two ASPs follow the same naming convention just because
#         get_document_xml happens to both be a plain "/xml" for each.
#         Response is raw PDF bytes, same as get_document_xml's raw XML text
#         above - just read via response.content instead of response.text.

#         Same id-extraction as get_document_xml: Marmin's own invoice id,
#         read out of the saved submit response (flat "id", or nested
#         "data"/"id" as a fallback), not doc.name or the Business Profile
#         ID."""
#         if not doc.custom_submit_response:
#             frappe.throw(_("Submit response not found in Invoice"))

#         response_data = json.loads(doc.custom_submit_response)
#         document_id = response_data.get("id") or response_data.get("data", {}).get("id")
#         if not document_id:
#             frappe.throw(_("Marmin invoice id not found in submit response"))

#         base_url = self.get_base_url()
#         resource = self._document_resource_path(doc)
#         url = f"{base_url}/api/{resource}/{document_id}/download-pdf"
#         headers = self.get_auth_headers()

#         response = requests.get(url, headers=headers)
#         if response.status_code == 200:
#             return response.content

#         frappe.throw(_("Marmin API Error: {0}").format(response.text))

#     # ---- webhook: SUBSCRIBING is dashboard-only, confirmed from
#     # docs.ae.marmin.ai/.../integration/webhooks/* - there is no API to
#     # register a webhook, view the subscription, or regenerate the signing
#     # secret; all three are done in the Marmin Web Application's Developer
#     # Dashboard > Webhooks tab, gated by OTP 2FA sent to your registered
#     # email. So register_webhook/get_subscription/get_webhook_deliveries
#     # below still can't be turned into real API calls the way Flick's
#     # were.
#     #
#     # RECEIVING a webhook is a different story, and IS documented (Webhook
#     # Payload Format + Webhook Signature Verification pages) - that's
#     # marmin_webhook_listener() below, the actual endpoint you paste into
#     # that dashboard's config screen. get_webhook_listener_url() gives you
#     # that URL to paste there.
#     _WEBHOOK_NOT_AN_API_MESSAGE = _(
#         "Marmin doesn't have a webhook subscription API - it's configured only "
#         "in the Marmin Web Application (Developer Dashboard > Webhooks tab), "
#         "gated by an OTP sent to your email. To set it up: paste this row's "
#         "Webhook URL into that dashboard as the endpoint, then Reveal/Regenerate "
#         "the Webhook Signing Secret there and paste it into this row's Webhook "
#         "Secret field. There's nothing to click here for that - Subscribe "
#         "Webhook / Get Subscription / Webhook Logs only exist for providers "
#         "(like Flick) that expose an actual API for it."
#     )

#     def register_webhook(self):
#         frappe.throw(self._WEBHOOK_NOT_AN_API_MESSAGE)

#     def get_subscription(self):
#         frappe.throw(self._WEBHOOK_NOT_AN_API_MESSAGE)

#     def get_webhook_deliveries(self):
#         frappe.throw(self._WEBHOOK_NOT_AN_API_MESSAGE)

#     def get_webhook_listener_url(self):
#         """The URL to paste into Marmin's Developer Dashboard > Webhooks
#         config screen as the endpoint. Was returning the BaseAdapter
#         default (None) until now, which left this row's Webhook URL field
#         blank even though _WEBHOOK_NOT_AN_API_MESSAGE above already told
#         you to paste "this row's Webhook URL" somewhere - there was
#         nothing there to paste. marmin_webhook_listener (below) is the
#         real, documented receiving endpoint."""
#         return frappe.utils.get_url(
#             "/api/method/uae_erpgulf.uae_erpgulf.providers.marmin.adapter.marmin_webhook_listener"
#         )

#     # ---- invoices: the one thing we do have real docs for ----
#     def submit_invoice(self, doctype, doc, json_data):
#         """POST /api/sales-invoices/{business_profile_id}

#         NOTE: Sales Invoice only for now - the docs page we have is
#         specifically "sale-invoices/create". Purchase Invoice needs its own
#         Marmin docs page before this can support it.
#         """
#         if doctype != "Sales Invoice":
#             frappe.throw(_("Marmin adapter only supports Sales Invoice submission so far."))
#         if doc.is_return:
#             return self._submit_credit_note(doc)

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

#         # This is the ONLY JSON Marmin actually receives - it has nothing to
#         # do with the Flick-shaped .json file attached to the Sales Invoice
#         # (that one's built once for every provider and only Flick's adapter
#         # uses it). save_outgoing_payload() (BaseAdapter) attaches it as its
#         # own file on the invoice, under the same Attachments list, so it's
#         # visible right after every submit attempt - success or failure.
#         self.save_outgoing_payload(doc, payload)

#         response = requests.post(url, headers=headers, json=payload, timeout=120)

#         try:
#             response_data = response.json()
#         except Exception:
#             response_data = response.text

#         return response.status_code, response_data

#     def _build_invoice_payload(self, doc):
#         """Maps a Sales Invoice to Marmin's flat JSON shape, per Marmin's own
#         schema (docs.ae.marmin.ai/.../sale-invoices/create) - this replaces an
#         earlier version that guessed field names (item_name/unit_price/
#         line_amount, and profile_execution_id as this row's docname) and got
#         a 400 back listing every one of them as wrong or missing. Only the
#         fields we're confident about are filled in here - Marmin's docs list
#         30+ further optional fields (delivery info, payment means,
#         allowances, etc.) that aren't mapped yet.

#         NOTE: this builds straight from the Sales Invoice document (doc),
#         not from json_data - json_data is the PEPPOL/UBL-style JSON built for
#         Flick, and Marmin's payload shape is a different, flat JSON, so
#         json_data isn't reused here (it's still accepted as a parameter to
#         match the shared submit_invoice interface every adapter uses).

#         invoice_type_code was a hardcoded "380" before - now it calls Flick's
#         own get_invoice_type_code(doc) (json_einvoice.py), which returns "480"
#         instead whenever custom_vat_category is "O - Not subject to VAT",
#         matching the same "380 or 480" Marmin's docs describe, instead of
#         always claiming every invoice is standard-rated.
#         """
#         default_vat_category = doc.custom_vat_category
#         default_vat_rate = doc.taxes[0].rate if doc.taxes else 0
#         default_exemption_label = doc.custom_vat_exemption_reason_code

#         return {
#             "profile_execution_id": MARMIN_PROFILE_EXECUTION_ID_STANDARD,
#             "document_number": doc.name,
#             "issue_date": str(doc.posting_date),
#             "invoice_type_code": get_invoice_type_code(doc),
#             "due_date": str(doc.due_date) if doc.due_date else str(doc.posting_date),
#             "document_currency_code": doc.currency,
#             "accounting_supplier_party": self._build_accounting_supplier_party(doc),
#             "accounting_customer_party": self._build_accounting_customer_party(doc),
#             "payment_means": self._build_payment_means(doc),
#             "document_lines": [
#                 self._build_invoice_line(
#                     item, default_vat_category, default_vat_rate, default_exemption_label
#                 )
#                 for item in doc.items
#             ],
#         }

#     def _submit_credit_note(self, doc):
#         """POST /api/sales-credit-notes/{business_profile_id} - confirmed via
#         a real curl example from Marmin's sale.credit_note.create docs page
#         (curl -X POST ".../api/sales-credit-notes/MBP-1234567890"), the same
#         shape as the invoice endpoint (sales-invoices -> sales-credit-notes,
#         same {business_profile_id} path segment, same POST) - it just wasn't
#         safe to assume that until this was actually confirmed rather than
#         guessed.

#         Mirrors submit_invoice's own request handling exactly (same auth
#         headers, same save_outgoing_payload call before sending, same
#         response.json()-or-text fallback, same (status_code, response_data)
#         return shape submit_invoice() and BaseAdapter's caller expect) -
#         _build_credit_note_payload(doc) above is the only thing specific to
#         a credit note here."""
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
#         url = f"{base_url}/api/sales-credit-notes/{business_profile_id}"
#         headers = self.get_auth_headers({"Content-Type": "application/json"})

#         payload = self._build_credit_note_payload(doc)

#         self.save_outgoing_payload(doc, payload)

#         response = requests.post(url, headers=headers, json=payload, timeout=120)

#         try:
#             response_data = response.json()
#         except Exception:
#             response_data = response.text

#         return response.status_code, response_data

#     def _build_credit_note_payload(self, doc):
#         """Maps a return Sales Invoice to Marmin's credit note JSON shape,
#         per the real example pasted from their sale.credit_note.create docs
#         page. Reuses the exact same building blocks _build_invoice_payload
#         already uses wherever the shapes agree (party blocks, payment
#         means, document lines) rather than re-deriving them a second way:

#         - accounting_supplier_party / accounting_customer_party: identical
#           blocks to the invoice payload (confirmed by the example - same
#           nested endpoint_id/postal_address/party_tax_scheme shape).
#         - payment_means: same _build_payment_means(doc) - the example's
#           payment_means entry (code "30" + payee_financial_account) matches
#           that method's own shape exactly.
#         - document_lines: same per-item mapping as _build_invoice_line -
#           the example's quantity/unit_code/description/name/price/
#           classified_tax_category fields all match what that method
#           already builds (order_line_reference in the example is skipped,
#           same as the invoice payload not mapping it - optional, no Sales
#           Invoice field it obviously maps to yet).
#         - credit_note_type_code: get_invoice_type_code(doc) - already
#           returns "381" for is_return, same code Marmin's example uses.
#         - document_number: mandatory (confirmed live - a 400 without it),
#           and NOT this credit note's own docname the way the invoice
#           payload's document_number is - it's the ORIGINAL invoice's
#           custom_document_id (Marmin's own assigned document id for that
#           invoice, the same field the webhook listener matches resource_id
#           against), read off doc.return_against. Throws if there's no
#           return_against, or if that original invoice hasn't actually been
#           submitted to Marmin yet (no custom_document_id to read).
#         - billing_reference: the same original invoice, built the same way
#           Flick's own document_references already is (build_uae_invoice_json,
#           json_einvoice.py) - id + issue_date straight off that Sales
#           Invoice. Always set alongside document_number now (both need the
#           same original_invoice lookup) - no more fallback to
#           custom_return_against_for_uae_einvoice, since that path can't
#           supply a custom_document_id for the now-mandatory document_number
#           either.
#         - discrepancy_response: doc.custom_credit_note_reason_code, split
#           the same way add_credit_note_details (json_einvoice.py) already
#           splits it for Flick - the example's value ("DL8.61.1.A") is just
#           the code half of that same field, not the code+reason pair.
#         - issue_date/issue_time/document_currency_code: same fields the
#           invoice payload already uses (issue_time via get_issue_time,
#           json_einvoice.py, for the HH:MM:SS format the example shows).

#         NOT mapped - present in the example but no confirmed mandatory/
#         optional split from docs prose (only this one JSON sample), and no
#         obvious source field on Sales Invoice for most of them: note,
#         accounting_cost, buyer_reference, invoice_period, order_reference,
#         delivery, project_reference, charges, allowances, payment_terms,
#         prepaid_amount, payable_rounding_amount, attachments,
#         document_source, and the separate flat-id buyer_customer_party/
#         seller_supplier_party blocks (unclear how these differ from
#         accounting_customer_party/accounting_supplier_party above, or
#         whether they need a Marmin Business Profile ID we may not have for
#         an external buyer). Same "fill in once confirmed" approach as
#         _build_invoice_payload's own unmapped-optional-fields note."""
#         default_vat_category = doc.custom_vat_category
#         default_vat_rate = doc.taxes[0].rate if doc.taxes else 0
#         default_exemption_label = doc.custom_vat_exemption_reason_code

#         payload = {
#             "profile_execution_id": MARMIN_PROFILE_EXECUTION_ID_STANDARD,
#             "issue_date": str(doc.posting_date),
#             "issue_time": get_issue_time(doc),
#             "credit_note_type_code": get_invoice_type_code(doc),
#             "document_currency_code": doc.currency,
#             "due_date": str(doc.due_date) if doc.due_date else str(doc.posting_date),
#             "accounting_supplier_party": self._build_accounting_supplier_party(doc),
#             "accounting_customer_party": self._build_accounting_customer_party(doc),
#             "payment_means": self._build_payment_means(doc),
#             "document_lines": [
#                 self._build_invoice_line(
#                     item, default_vat_category, default_vat_rate, default_exemption_label
#                 )
#                 for item in doc.items
#             ],
#         }

#         # document_number is mandatory (confirmed live: Marmin rejected a
#         # credit note with no document_number at all with a 400 -
#         # "Document number is mandatory when auto numbering is disabled").
#         # Unlike the invoice payload, where document_number is just this
#         # document's own name, a credit note's document_number is the
#         # ORIGINAL invoice's Marmin-assigned document id - custom_document_id
#         # on that Sales Invoice (the same field the webhook listener above
#         # matches resource_id against), not this credit note's own docname
#         # and not the "id" get_document_xml/get_document_pdf read out of a
#         # submit response. Only available when return_against links to a
#         # real Sales Invoice in this system that has actually been
#         # submitted to Marmin already - throws with a clear reason for
#         # either gap rather than sending an empty/wrong value and getting
#         # another opaque 400 back.
#         if not doc.return_against:
#             frappe.throw(
#                 _(
#                     "This credit note has no Return Against invoice set - Marmin "
#                     "requires the original invoice's Document ID as document_number "
#                     "for a credit note, and there's no Sales Invoice here to read it "
#                     "from."
#                 )
#             )
#         original_invoice = frappe.get_doc("Sales Invoice", doc.return_against)
#         if not original_invoice.custom_document_id:
#             frappe.throw(
#                 _(
#                     "Original invoice {0} has no Document ID (custom_document_id) yet - "
#                     "it needs to have been successfully submitted to Marmin first, so "
#                     "this credit note can reference its Marmin document id as "
#                     "document_number."
#                 ).format(original_invoice.name)
#             )
#         payload["document_number"] = original_invoice.custom_document_id
#         payload["billing_reference"] = [
#             {
#                 "id": original_invoice.name,
#                 "issue_date": str(original_invoice.posting_date),
#             }
#         ]

#         raw_reason = doc.custom_credit_note_reason_code
#         if raw_reason:
#             code, _sep, _reason = raw_reason.partition("-")
#             payload["discrepancy_response"] = code.strip()

#         return payload

#     def _build_payment_means(self, doc):
#         """Build payment_means by reusing Flick's own get_payment_means(doc)
#         (json_einvoice.py) - the one real derivation from this invoice's
#         Payments table -> Mode of Payment -> Accounts, instead of a second,
#         parallel copy of that same lookup living here too. Whatever that
#         function returns (it loops doc.payments and reads bank details off
#         each row's Mode of Payment) is what this adapter reshapes into
#         Marmin's payment_means entries - nothing here is invented.

#         Real data always wins: if the invoice has a Payments row with a
#         Mode of Payment that carries a valid code, that's what gets sent.
#         MARMIN_DEFAULT_PAYMENT_MEANS_CODE only kicks in when
#         get_payment_means(doc) comes back completely empty (no Payments
#         row at all, or a Mode of Payment with no code configured) -
#         confirmed necessary, not just theoretical, since Marmin rejects a
#         submission outright (400, "At least one payment means is
#         mandatory") when payment_means is an empty array. So this isn't a
#         silent stand-in for real data that exists but wasn't read
#         correctly - it only ever fires when there's genuinely nothing on
#         the invoice to derive from.

#         Still validates each code against MARMIN_APPROVED_PAYMENT_MEANS_CODES
#         - that's a real constraint from Marmin's own docs (a different, and
#         narrower, list than PEPPOL's, which get_payment_means itself doesn't
#         restrict against), so a code that's fine for Flick but not Marmin
#         still throws here with a clear message, instead of bouncing back as
#         an opaque 400 from Marmin's side."""
#         entries = []

#         for pm in get_payment_means(doc):
#             payment_code = (pm.get("payment_means_code") or "").strip()
#             if not payment_code:
#                 continue

#             if payment_code not in MARMIN_APPROVED_PAYMENT_MEANS_CODES:
#                 frappe.throw(
#                     _(
#                         "This invoice's payment means code '{0}' isn't one Marmin "
#                         "accepts ({1}). Update the Mode of Payment's Payment Means "
#                         "Code to a supported one."
#                     ).format(
#                         payment_code,
#                         ", ".join(sorted(MARMIN_APPROVED_PAYMENT_MEANS_CODES)),
#                     )
#                 )

#             entry = {"payment_means_code": payment_code}

#             if payment_code == "30":
#                 payee_account = pm.get("payee_financial_account") or {}
#                 if not payee_account.get("id"):
#                     frappe.throw(
#                         _(
#                             "This invoice's Mode of Payment needs a bank Account under "
#                             "its Accounts table - Marmin requires payee_financial_account "
#                             "for payment means code 30."
#                         )
#                     )
#                 entry["payee_financial_account"] = {
#                     "id": payee_account.get("id"),
#                     "name": payee_account.get("name"),
#                 }
#             elif payment_code in ("54", "55", "49"):
#                 # card_account (54/55) and payment_mandate (49) aren't wired
#                 # up - get_payment_means only fills in placeholder card
#                 # details (a fake card number/network), and sending those to
#                 # Marmin isn't better than a clear error telling you this
#                 # combination isn't supported yet.
#                 frappe.throw(
#                     _(
#                         "This invoice's Mode of Payment uses payment means code {0}, "
#                         "which needs card_account or payment_mandate details this "
#                         "adapter doesn't build yet - use a bank transfer (30) or cash "
#                         "(10) Mode of Payment instead, or ask to have this one filled "
#                         "in."
#                     ).format(payment_code)
#                 )

#             entries.append(entry)

#         if not entries:
#             entries = [{"payment_means_code": MARMIN_DEFAULT_PAYMENT_MEANS_CODE}]

#         return entries

#     def _build_accounting_supplier_party(self, doc):
#         """Seller party block, built from the Company doctype - this was
#         missing entirely before, which is exactly why Marmin's 400 said
#         accounting_supplier_party and accounting_customer_party "cannot be
#         the same entity" (with nothing sent for the supplier side, Marmin
#         had nothing to tell it apart from the buyer).

#         NOTE: an earlier version of this mirrored Flick's own
#         update_participant() (providers/flick/adapter.py), reading
#         company_doc.custom_peppol_id / custom_street_address / etc. That
#         crashed with AttributeError - Company has NO such fields at all
#         (confirmed against fixtures/custom_field.json: Company only carries
#         the 5 e-invoicing toggle fields), so update_participant() was
#         apparently always dead code, never actually invoked (the only
#         thing that ever called it, participant.py's update_flick_participant
#         wrapper, had zero real callers of its own anywhere in the app - that
#         file has since been removed).

#         So this now uses only real data: endpoint_id is this row's own
#         Participant ID (the Business Profile ID Marmin already knows this
#         company by - same field submit_invoice() already uses for the URL),
#         and the postal address/contact details come from the Company's
#         actual linked Address record, via frappe's core get_default_address()
#         - the same Address doctype and same fields (address_line1,
#         emirate, email_id, phone, ...) the buyer side below already reads
#         successfully, since Company doesn't have inline address fields any
#         more than Customer does."""
#         from frappe.contacts.doctype.address.address import get_default_address

#         company_doc = frappe.get_doc("Company", doc.company)

#         endpoint_id = self.settings.participant_id
#         if not endpoint_id:
#             frappe.throw(
#                 _(
#                     "Participant ID (Business Profile ID) is missing on "
#                     "E-Invoice Provider Settings - Marmin requires it as "
#                     "this invoice's accounting_supplier_party.endpoint_id."
#                 )
#             )

#         address_name = get_default_address("Company", company_doc.name)
#         if not address_name:
#             frappe.throw(
#                 _(
#                     "Company {0} has no Address linked to it - Marmin "
#                     "requires a postal_address on accounting_supplier_party. "
#                     "Add one under Company > Address and Contacts."
#                 ).format(company_doc.name)
#             )
#         address_data = frappe.get_doc("Address", address_name)

#         country_dict = country_code_mapping()
#         country_code = "AE"
#         if address_data.country and address_data.country.lower() in country_dict:
#             country_code = country_dict[address_data.country.lower()]

#         country_subentity = get_uae_emirate_code(address_data.emirate)
#         if country_code == "AE" and not country_subentity:
#             frappe.throw(
#                 _(
#                     "Company {0}'s address needs a recognised UAE emirate "
#                     "(Abu Dhabi, Dubai, Sharjah, Ajman, Umm Al Quwain, Ras Al "
#                     "Khaimah or Fujairah) - Marmin requires this for the "
#                     "supplier's postal address."
#                 ).format(company_doc.name)
#             )

#         # Marmin's schema notes call telephone mandatory specifically for
#         # UAE suppliers (unlike the buyer side, where it's not required).
#         if country_code == "AE" and not address_data.phone:
#             frappe.throw(
#                 _(
#                     "Company {0}'s Address has no Phone set - Marmin "
#                     "requires a telephone number on accounting_supplier_party "
#                     "for UAE suppliers."
#                 ).format(company_doc.name)
#             )

#         party = {
#             "name": company_doc.company_name,
#             "party_name": company_doc.company_name,
#             # profile_id: Marmin's own internal Business Profile reference
#             # for this party (separate from endpoint_id, which is the
#             # PEPPOL network identifier) - same value already used for the
#             # submit URL and as endpoint_id above, since that IS this
#             # company's Business Profile ID. Not set on the buyer side
#             # (_build_accounting_customer_party) - we don't have a Marmin
#             # profile_id for an external buyer, only their PEPPOL endpoint
#             # id, and there's no confirmed docs page yet saying that's
#             # required for a non-Marmin-registered buyer.
#             "profile_id": self.settings.participant_id,
#             "endpoint_id": endpoint_id,
#             "endpoint_scheme_id": MARMIN_ENDPOINT_SCHEME_ID_UAE,
#             "email": address_data.email_id,
#             "telephone": address_data.phone,
#             "postal_address": {
#                 "street_name": address_data.address_line1,
#                 "additional_street_name": address_data.address_line2,
#                 "city_name": address_data.city,
#                 "postal_zone": address_data.pincode,
#                 "country_subentity": country_subentity,
#                 "country": address_data.country or "United Arab Emirates",
#                 "country_code": country_code,
#             },
#         }

#         # tax_id is Company's standard "Tax ID" field (not a custom_* one) -
#         # same TRN value doubling as Marmin's "tin" and party_tax_scheme.
#         if company_doc.tax_id:
#             party["tin"] = company_doc.tax_id
#             party["party_tax_scheme"] = {
#                 "company_id": company_doc.tax_id,
#                 "tax_scheme": "VAT",
#             }

#         return party

#     def _build_accounting_customer_party(self, doc):
#         """Buyer party block, built from the same Customer + Address fields
#         Flick's own PEPPOL builder already reads (build_uae_invoice_json in
#         json_einvoice.py) - custom_peppol_id as the buyer's endpoint id,
#         tax_id as its VAT number, and the customer's primary/invoice address
#         for postal_address. Marmin just wants all of it nested under
#         accounting_customer_party instead of flat."""
#         customer_doc = frappe.get_doc("Customer", doc.customer)

#         address_data = None
#         if doc.customer_address:
#             address_data = frappe.get_doc("Address", doc.customer_address)
#         elif customer_doc.customer_primary_address:
#             address_data = frappe.get_doc("Address", customer_doc.customer_primary_address)
#         if not address_data:
#             frappe.throw(_("Customer address not found for {0}").format(doc.customer))

#         country_dict = country_code_mapping()
#         country_code = "AE"
#         if address_data.country and address_data.country.lower() in country_dict:
#             country_code = country_dict[address_data.country.lower()]

#         country_subentity = get_uae_emirate_code(address_data.emirate)
#         if country_code == "AE" and not country_subentity:
#             frappe.throw(
#                 _(
#                     "Customer {0}'s address needs a recognised UAE emirate (Abu Dhabi, "
#                     "Dubai, Sharjah, Ajman, Umm Al Quwain, Ras Al Khaimah or Fujairah) - "
#                     "Marmin requires this for the buyer's postal address."
#                 ).format(doc.customer)
#             )

#         endpoint_id = customer_doc.custom_peppol_id
#         if not endpoint_id:
#             frappe.throw(
#                 _(
#                     "Customer {0} has no PEPPOL ID (Participant ID) set - Marmin "
#                     "requires one on accounting_customer_party.endpoint_id for every "
#                     "invoice. Set it on the Customer the same way it's already set "
#                     "for Flick."
#                 ).format(doc.customer)
#             )

#         party = {
#             "name": customer_doc.customer_name,
#             "party_name": customer_doc.customer_name,
#             "endpoint_id": endpoint_id,
#             "endpoint_scheme_id": MARMIN_ENDPOINT_SCHEME_ID_UAE,
#             "email": address_data.email_id,
#             "postal_address": {
#                 "street_name": address_data.address_line1,
#                 "additional_street_name": address_data.address_line2,
#                 "city_name": address_data.city,
#                 "postal_zone": address_data.pincode,
#                 "country_subentity": country_subentity,
#                 "country": address_data.country or "United Arab Emirates",
#                 "country_code": country_code,
#             },
#         }

#         # tax_id doubles as both the "VAT identifier" alternative Marmin
#         # accepts instead of a buyer identifier on non-export invoices, and
#         # the party_tax_scheme.company_id their schema separately asks for -
#         # same single field Flick's builder already uses as vat_number.
#         if customer_doc.tax_id:
#             party["tin"] = customer_doc.tax_id
#             party["party_tax_scheme"] = {
#                 "company_id": customer_doc.tax_id,
#                 "tax_scheme": "VAT",
#             }

#         return party

#     def _build_invoice_line(
#         self, item, default_vat_category, default_vat_rate, default_exemption_label
#     ):
#         """One document_lines entry. classified_tax_category reuses the same
#         custom_vat_category labels (and per-item Item Tax Template override)
#         that the Flick/PEPPOL builder in json_einvoice.py already uses via
#         get_vat_category_code() - so both providers agree on what "standard
#         rated", "zero rated", etc. mean for this company, instead of Marmin
#         inventing its own second mapping. Same for the exemption reason
#         (custom_vat_exemption_reason_code) Marmin requires whenever the
#         category comes out "E" (exempt)."""
#         vat_category = default_vat_category
#         tax_rate = default_vat_rate
#         exemption_label = default_exemption_label

#         if item.item_tax_template:
#             item_tax_template = frappe.get_doc("Item Tax Template", item.item_tax_template)
#             vat_category = item_tax_template.custom_vat_category or default_vat_category
#             exemption_label = (
#                 item_tax_template.custom_vat_exemption_reason_code or default_exemption_label
#             )
#             if item_tax_template.taxes:
#                 tax_rate = item_tax_template.taxes[0].tax_rate

#         vat_code = get_vat_category_code(vat_category) if vat_category else "S"

#         classified_tax_category = {
#             "id": vat_code,
#             "percent": float(tax_rate or 0),
#             "tax_scheme": "VAT",
#         }

#         if vat_code == "E":
#             # Marmin requires both a code and a description here whenever the
#             # category is Exempt - custom_vat_exemption_reason_code stores
#             # something like "VATEX-AE-32-1 - Public postal services", so
#             # split on the first " - " to get code vs. description the same
#             # way the Flick/PEPPOL builder already does for its own field.
#             if not exemption_label:
#                 frappe.throw(
#                     _(
#                         "Item {0} is VAT-exempt but has no VAT Exemption Reason Code set "
#                         "(on its Item Tax Template or on this Sales Invoice) - Marmin "
#                         "requires one for exempt lines."
#                     ).format(item.item_code)
#                 )
#             code, _sep, description = exemption_label.partition(" - ")
#             classified_tax_category["tax_exemption_reason_code"] = code.strip()
#             classified_tax_category["tax_exemption_reason"] = (description or exemption_label).strip()

#         return {
#             "name": item.item_name,
#             "description": item.description or item.item_name,
#             "quantity": item.qty,
#             "unit_code": self._unit_code(item.uom),
#             "price": {
#                 "base_amount": item.rate,
#                 "base_quantity": 1,
#             },
#             "classified_tax_category": classified_tax_category,
#         }

#     def _unit_code(self, uom):
#         if not uom:
#             return "EA"
#         return MARMIN_UOM_TO_UNECE_CODE.get(uom.strip().lower(), "EA")


# # ---- webhook listener ----
# # Everything below is the RECEIVING side of Marmin's webhook (see
# # get_webhook_listener_url above for the SUBSCRIBING side, still
# # dashboard-only). Confirmed against the real "Webhook Payload Format" and
# # "Webhook Signature Verification" docs pages, pasted directly into this
# # conversation.

# # Header Marmin sends the webhook signature in - NOT actually confirmed
# # against the "Webhook Signature Verification" docs page. That page's code
# # sample only showed the verification function itself (HMAC-SHA256,
# # base64, compared against a receivedSignature argument) - it didn't show
# # where receivedSignature comes from on the real HTTP request. Using the
# # same header name Marmin's own token endpoint already uses for its own
# # HMAC signature (x-marmin-signature - see _fetch_token above) as a
# # reasoned best guess, since it's their established convention for "an
# # HMAC signature goes in this header" elsewhere in this same API - but
# # this specific value is NOT verified for webhooks. If real deliveries
# # get rejected (or, worse, silently accepted without a valid signature)
# # once this is live, check the exact header name against that docs page
# # and fix this constant rather than leaving it silently wrong.
# MARMIN_WEBHOOK_SIGNATURE_HEADER = "x-marmin-signature"


# def _verify_marmin_webhook_signature(raw_body, received_signature, webhook_secret):
#     """HMAC-SHA256(key=webhook_secret, message=raw_body), base64-encoded -
#     this is exactly Marmin's own verifyWebhookSignature function from
#     their Webhook Signature Verification docs page, translated from the
#     JS sample given there.

#     raw_body must be the exact raw bytes of the request body, not
#     re-serialized JSON - HMACs are byte-exact, so parsing the payload and
#     re-encoding it before hashing would silently break verification
#     against a real, unmodified delivery (different key order or
#     whitespace produces a different signature even though the data is
#     "the same")."""
#     if not received_signature or not webhook_secret:
#         return False

#     body_bytes = raw_body if isinstance(raw_body, bytes) else raw_body.encode("utf-8")
#     expected_signature = base64.b64encode(
#         hmac.new(webhook_secret.encode("utf-8"), body_bytes, hashlib.sha256).digest()
#     ).decode("utf-8")

#     return hmac.compare_digest(expected_signature, received_signature)


# @frappe.whitelist(allow_guest=True)  # nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method
# def marmin_webhook_listener():
#     """Listener for Marmin's webhook events - the URL
#     get_webhook_listener_url() above hands you to paste into the Marmin
#     Web Application's Developer Dashboard > Webhooks config screen.

#     Confirmed against the real docs pages pasted directly into this
#     conversation:
#     - Webhook Payload Format: {org_id, event_type, profile_id,
#       resource_id, resource_url, event_timestamp, webhook_event_id}.
#       Notably NOT shaped like Flick's payload, which embeds the new
#       status directly - Marmin's is only a notification that SOMETHING
#       changed on resource_id (Marmin's own invoice id, the same one
#       get_document_xml/get_document_status/get_document_pdf all key off
#       already), with no status field of its own. So this listener
#       re-fetches the real current status itself via peppol-status-logs
#       (same endpoint/derivation "Get Document Status" already uses)
#       rather than trusting anything in the payload body about what
#       actually changed.
#     - Webhook Signature Verification: see _verify_marmin_webhook_signature
#       above.

#     NOT yet confirmed - fill in once you have the real docs page content:
#     - MARMIN_WEBHOOK_SIGNATURE_HEADER's exact value (see its own comment
#       above).
#     - The exact success response body/status Marmin's "Expected Response"
#       docs page wants, and what "Delivery & Retry Behavior" actually does
#       on anything else - this returns a plain 200 + small JSON body for
#       now, matching flick_webhook_listener's own convention, not checked
#       against those two specific docs pages yet.
#     """
#     raw_body = frappe.request.get_data()  # raw bytes - see the signature note above

#     try:
#         payload = json.loads(raw_body)
#     except Exception:
#         frappe.log_error(frappe.get_traceback(), "Marmin Webhook Invalid JSON")
#         frappe.local.response["http_status_code"] = 400
#         return {"received": False, "error": "invalid JSON"}

#     profile_id = payload.get("profile_id")
#     resource_id = payload.get("resource_id")
#     event_type = payload.get("event_type")
#     webhook_event_id = payload.get("webhook_event_id")

#     # profile_id is Marmin's Business Profile ID - the same value stored
#     # in Participant ID on this company's E-Invoice Provider Settings row
#     # (see get_participant_details above), so it's what identifies WHICH
#     # row's Webhook Secret to check this delivery's signature against.
#     settings_name = frappe.db.get_value(
#         "E-Invoice Provider Settings",
#         {"provider": "Marmin AI Software Design LLC", "participant_id": profile_id},
#         "name",
#     )
#     if not settings_name:
#         frappe.log_error(
#             f"No E-Invoice Provider Settings row found for Marmin profile_id "
#             f"{profile_id} (webhook_event_id {webhook_event_id})",
#             "Marmin Webhook Unknown Profile",
#         )
#         frappe.local.response["http_status_code"] = 404
#         return {"received": False, "error": "unknown profile_id"}

#     settings = frappe.get_doc("E-Invoice Provider Settings", settings_name)
#     webhook_secret = settings.get_password("webhook_secret")
#     received_signature = frappe.request.headers.get(MARMIN_WEBHOOK_SIGNATURE_HEADER)

#     if not _verify_marmin_webhook_signature(raw_body, received_signature, webhook_secret):
#         # Reject rather than silently trust an unverifiable payload just
#         # because its shape looks right - if this constant's header name
#         # turns out to be wrong, every real delivery ends up here, which
#         # is exactly the loud, checkable failure mode you want instead of
#         # quietly accepting forged status updates.
#         frappe.log_error(
#             f"Signature check failed for Marmin webhook_event_id "
#             f"{webhook_event_id} (profile_id {profile_id}) - header "
#             f"checked: {MARMIN_WEBHOOK_SIGNATURE_HEADER}",
#             "Marmin Webhook Signature Mismatch",
#         )
#         frappe.local.response["http_status_code"] = 401
#         return {"received": False, "error": "signature verification failed"}

#     # Find which local document this resource_id actually is FIRST - needed
#     # to know whether it's a credit note (its Marmin id lives under
#     # sales-credit-notes, not sales-invoices - see _document_resource_path)
#     # before making the status-log call below, not after.
#     sales_invoice_row = frappe.db.get_value(
#         "Sales Invoice", {"custom_document_id": resource_id}, ["name", "is_return"], as_dict=True
#     )
#     # Marmin doesn't support Purchase Invoice submission yet (submit_invoice
#     # above throws for anything but Sales Invoice) - checking here too
#     # costs nothing and keeps this symmetric with flick_webhook_listener,
#     # for whenever that changes. No credit-note concept for Purchase
#     # Invoice here yet either, so it always reads as an invoice.
#     purchase_invoice_name = frappe.db.get_value(
#         "Purchase Invoice", {"custom_document_id": resource_id}, "name"
#     )

#     is_return = bool(sales_invoice_row and sales_invoice_row.is_return)
#     resource_path = "sales-credit-notes" if is_return else "sales-invoices"

#     # Signature verified - now find out what actually changed, since the
#     # payload itself doesn't say.
#     adapter = MarminAdapter(settings)
#     reporting_status = None
#     try:
#         base_url = adapter.get_base_url()
#         url = f"{base_url}/api/{resource_path}/{resource_id}/peppol-status-logs"
#         response = requests.get(url, headers=adapter.get_auth_headers())
#         try:
#             status_log_body = response.json()
#         except Exception:
#             status_log_body = response.text
#         if isinstance(status_log_body, list):
#             reporting_status = MarminAdapter._reporting_status_from_status_logs(
#                 status_log_body
#             )
#     except Exception:
#         frappe.log_error(frappe.get_traceback(), "Marmin Webhook Status Refetch Error")

#     frappe.get_doc(
#         {
#             "doctype": "UAE E-Invoice Webhook Logs",
#             "webhook_response": raw_body.decode("utf-8", errors="replace"),
#             "document_id": resource_id,
#             "participant_id": profile_id,
#             "event_type": event_type,
#             "reporting_status": reporting_status,
#         }
#     ).insert(ignore_permissions=True)

#     if resource_id and reporting_status:
#         if sales_invoice_row:
#             frappe.db.set_value(
#                 "Sales Invoice",
#                 sales_invoice_row.name,
#                 "custom_reporting_status",
#                 reporting_status,
#             )

#         if purchase_invoice_name:
#             frappe.db.set_value(
#                 "Purchase Invoice",
#                 purchase_invoice_name,
#                 "custom_reporting_status",
#                 reporting_status,
#             )

#     frappe.db.commit()  # nosemgrep: frappe-manual-commit

#     return {"received": True, "processed": True}

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
    get_payment_means,
    get_issue_time,
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
# Marmin accepts. This is a real constraint from Marmin's own docs, not a
# guessed value.
#
# "1" (UNCL4461 "Instrument not defined") is used as a LAST-RESORT fallback
# only - confirmed necessary the hard way: an invoice with no real payment
# data sent an empty payment_means array and Marmin rejected the whole
# submission with a 400 ("At least one payment means is mandatory"), since
# it's a mandatory field with no concept of "not applicable". So
# _build_payment_means below always tries get_payment_means(doc) (Flick's
# own real Payments-table derivation) FIRST, and only reaches for this
# static code when that comes back completely empty - real data from the
# invoice always wins over this default when it's actually there.
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

    # Marmin's XML (and possibly PDF - same async document pipeline) is
    # generated some time after an invoice is accepted, so a "not generated
    # yet" response right after submit is normal, not a bug. This used to be
    # False specifically because PDF had no documented endpoint at all -
    # now that both get_document_xml and get_document_pdf are implemented
    # (see below), it's back to the base class default (True): test.py's
    # generate_and_send_einvoice tries both automatically right after a
    # successful submit, exactly like it always has for Flick. If Marmin
    # hasn't actually finished generating one yet, that attempt now just
    # gets logged quietly (see the fix in test.py/attach.py that shows the
    # real reason instead of a scary generic error) rather than disrupting
    # the submit - so trying automatically costs nothing on a "not ready"
    # response, and saves a manual click whenever Marmin happens to be
    # ready immediately. The "Get Document XML"/"Get Document PDF" buttons
    # in sales_invoice.js are still there as a manual fallback/retry.

    # Marmin's own generation delay is exactly the case
    # DOCUMENT_FETCH_RETRY_ATTEMPTS/DELAY_SECONDS (providers/base.py) exist
    # for - give the immediate-after-submit auto-fetch a few short-spaced
    # tries before falling back to "log it and let the manual buttons
    # handle it later". NOT a confirmed number from Marmin's docs (no docs
    # page states a generation SLA) - 3 tries, 5 seconds apart (~10s worst
    # case added to a submit that would otherwise fail this step anyway) is
    # a starting guess, tune it if documents still aren't ready by then or
    # if this is adding more delay than you want on every submission.
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

    def _document_resource_path(self, doc):
        """"sales-invoices" or "sales-credit-notes" - which of Marmin's two
        resource collections this document's own Marmin id (the "id" saved
        in custom_submit_response) actually lives under.

        Confirmed for the submit side only: invoices go to
        POST /api/sales-invoices/{business_profile_id}, credit notes to
        POST /api/sales-credit-notes/{business_profile_id} (real curl
        example from Marmin's docs). This method extends that same
        substitution to the READ side (peppol-status-logs/xml/download-pdf)
        by inference, not a separately confirmed docs page for each - a
        credit note's status/xml/pdf 200-ing with an empty/wrong result
        under sales-invoices/{id} (rather than a 404) is exactly what you'd
        see if that id only exists under sales-credit-notes instead, which
        is the whole reason this exists. If a read-side call ever comes
        back wrong even after using the right resource path here, that's
        the next thing to check against Marmin's own docs for that specific
        endpoint."""
        return "sales-credit-notes" if doc.is_return else "sales-invoices"

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
        header, that's the first thing to try removing.

        Return shape: always {"http_status": <int>, "response": <body>},
        success or failure - this used to frappe.throw() on a non-200
        instead of returning, which meant a failure here escaped as Frappe's
        own generic red error dialog (no HTTP status, no real detail) rather
        than the "Get Document Status" button's own dialog in
        sales_invoice.js. Returning the status code alongside the body lets
        that dialog show both, and decide its own colour instead of Frappe
        picking one for it."""
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

        # Unlike Flick, whose response has a flat reporting_status field,
        # Marmin's peppol-status-logs response is a plain chronological log
        # ({event, message, timestamp} entries) with no status field at
        # all - so derive one, the same "reported"/"pending"/"failed"/"not
        # reported" vocabulary badge_sales.js already keys the FTA badge
        # off of (custom_reporting_status), so the badge works for Marmin
        # invoices too instead of never getting set. Only meaningful when
        # the response actually is that list shape - a non-200 error body,
        # or some other shape, leaves this key out entirely.
        if isinstance(body, list):
            derived = self._reporting_status_from_status_logs(body)
            if derived:
                result["reporting_status"] = derived

        return result

    @staticmethod
    def _reporting_status_from_status_logs(events):
        """Best-effort derivation of a reporting_status from Marmin's
        peppol-status-logs event list. This list uses UAE PEPPOL 5-corner
        terminology: C2 is this document's own sending access point (i.e.
        Marmin itself here), C3 is the buyer's access point, and C5 is the
        FTA - the UAE model's own "5th corner" tax authority node. MLS
        means Message Level Status, PEPPOL's standard delivery-receipt
        concept.

        ONLY the "reported" branch below is confirmed, against one real,
        fully-successful invoice's log: its last two entries were both
        event "MLS_RECEIVED_FROM_C5", the final one with message "Received
        MLS from C5 with AP response. Marked the document as sent" - i.e.
        Marmin's own signal that the FTA has acknowledged the document.

        The "failed"/"pending"/"not reported" branches are a reasonable
        heuristic built from that same vocabulary (an event name so far
        always describes what happened using "_TO_C5"/"_FROM_C5"/etc.),
        NOT confirmed against a real failed or pending example, or any
        Marmin docs page listing every possible event/message - there's no
        docs page for this endpoint's response shape at all, only the
        sandbox curl example showing the request. If a real failure or
        pending case ever comes through and lands in the wrong bucket
        here, share that log's exact events/messages and this can be
        tightened against real evidence instead of guesswork."""
        if not isinstance(events, list) or not events:
            return None

        # Sort defensively by timestamp - "the latest state" only means
        # something if this is genuinely chronological, and nothing
        # guarantees the ASP always returns it already sorted.
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

        # Heuristic: queued to or transmitted toward the FTA (C5), but no
        # MLS response back from it yet - still in flight.
        if "to_c5" in haystack or "to c5" in haystack:
            return "pending"

        # Heuristic: nothing in this log even mentions C5 (the FTA) yet.
        return "not reported"

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
        resource = self._document_resource_path(doc)
        url = f"{base_url}/api/{resource}/{document_id}/xml"
        headers = self.get_auth_headers()

        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.text

        frappe.throw(_("Marmin API Error: {0}").format(response.text))

    def get_document_pdf(self, doctype, doc):
        """GET /api/sales-invoices/{id}/download-pdf - confirmed docs
        example (sandbox: curl .../api/sales-invoices/{id}/download-pdf -H
        "Authorization: Bearer <token>"). Note the path is "download-pdf",
        not just "/pdf" the way Flick's own PDF endpoint is shaped - don't
        assume the two ASPs follow the same naming convention just because
        get_document_xml happens to both be a plain "/xml" for each.
        Response is raw PDF bytes, same as get_document_xml's raw XML text
        above - just read via response.content instead of response.text.

        Same id-extraction as get_document_xml: Marmin's own invoice id,
        read out of the saved submit response (flat "id", or nested
        "data"/"id" as a fallback), not doc.name or the Business Profile
        ID."""
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

    # ---- webhook: SUBSCRIBING is dashboard-only, confirmed from
    # docs.ae.marmin.ai/.../integration/webhooks/* - there is no API to
    # register a webhook, view the subscription, or regenerate the signing
    # secret; all three are done in the Marmin Web Application's Developer
    # Dashboard > Webhooks tab, gated by OTP 2FA sent to your registered
    # email. So register_webhook/get_subscription/get_webhook_deliveries
    # below still can't be turned into real API calls the way Flick's
    # were.
    #
    # RECEIVING a webhook is a different story, and IS documented (Webhook
    # Payload Format + Webhook Signature Verification pages) - that's
    # marmin_webhook_listener() below, the actual endpoint you paste into
    # that dashboard's config screen. get_webhook_listener_url() gives you
    # that URL to paste there.
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
        """The URL to paste into Marmin's Developer Dashboard > Webhooks
        config screen as the endpoint. Was returning the BaseAdapter
        default (None) until now, which left this row's Webhook URL field
        blank even though _WEBHOOK_NOT_AN_API_MESSAGE above already told
        you to paste "this row's Webhook URL" somewhere - there was
        nothing there to paste. marmin_webhook_listener (below) is the
        real, documented receiving endpoint."""
        return frappe.utils.get_url(
            "/api/method/uae_erpgulf.uae_erpgulf.providers.marmin.adapter.marmin_webhook_listener"
        )

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

    def _submit_credit_note(self, doc):
        """POST /api/sales-credit-notes/{business_profile_id} - confirmed via
        a real curl example from Marmin's sale.credit_note.create docs page
        (curl -X POST ".../api/sales-credit-notes/MBP-1234567890"), the same
        shape as the invoice endpoint (sales-invoices -> sales-credit-notes,
        same {business_profile_id} path segment, same POST) - it just wasn't
        safe to assume that until this was actually confirmed rather than
        guessed.

        Mirrors submit_invoice's own request handling exactly (same auth
        headers, same save_outgoing_payload call before sending, same
        response.json()-or-text fallback, same (status_code, response_data)
        return shape submit_invoice() and BaseAdapter's caller expect) -
        _build_credit_note_payload(doc) above is the only thing specific to
        a credit note here."""
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
        """Maps a return Sales Invoice to Marmin's credit note JSON shape,
        per the real example pasted from their sale.credit_note.create docs
        page. Reuses the exact same building blocks _build_invoice_payload
        already uses wherever the shapes agree (party blocks, payment
        means, document lines) rather than re-deriving them a second way:

        - accounting_supplier_party / accounting_customer_party: identical
          blocks to the invoice payload (confirmed by the example - same
          nested endpoint_id/postal_address/party_tax_scheme shape).
        - payment_means: same _build_payment_means(doc) - the example's
          payment_means entry (code "30" + payee_financial_account) matches
          that method's own shape exactly.
        - document_lines: same per-item mapping as _build_invoice_line -
          the example's quantity/unit_code/description/name/price/
          classified_tax_category fields all match what that method
          already builds (order_line_reference in the example is skipped,
          same as the invoice payload not mapping it - optional, no Sales
          Invoice field it obviously maps to yet).
        - credit_note_type_code: get_invoice_type_code(doc) - already
          returns "381" for is_return, same code Marmin's example uses.
        - document_number: mandatory (confirmed live - a 400 without it),
          and NOT this credit note's own docname the way the invoice
          payload's document_number is - it's the ORIGINAL invoice's
          custom_document_id (Marmin's own assigned document id for that
          invoice, the same field the webhook listener matches resource_id
          against), read off doc.return_against. Throws if there's no
          return_against, or if that original invoice hasn't actually been
          submitted to Marmin yet (no custom_document_id to read).
        - billing_reference: the same original invoice, built the same way
          Flick's own document_references already is (build_uae_invoice_json,
          json_einvoice.py) - id + issue_date straight off that Sales
          Invoice. Always set alongside document_number now (both need the
          same original_invoice lookup) - no more fallback to
          custom_return_against_for_uae_einvoice, since that path can't
          supply a custom_document_id for the now-mandatory document_number
          either.
        - discrepancy_response: doc.custom_credit_note_reason_code, split
          the same way add_credit_note_details (json_einvoice.py) already
          splits it for Flick - the example's value ("DL8.61.1.A") is just
          the code half of that same field, not the code+reason pair.
        - issue_date/issue_time/document_currency_code: same fields the
          invoice payload already uses (issue_time via get_issue_time,
          json_einvoice.py, for the HH:MM:SS format the example shows).

        NOT mapped - present in the example but no confirmed mandatory/
        optional split from docs prose (only this one JSON sample), and no
        obvious source field on Sales Invoice for most of them: note,
        accounting_cost, buyer_reference, invoice_period, order_reference,
        delivery, project_reference, charges, allowances, payment_terms,
        prepaid_amount, payable_rounding_amount, attachments,
        document_source, and the separate flat-id buyer_customer_party/
        seller_supplier_party blocks (unclear how these differ from
        accounting_customer_party/accounting_supplier_party above, or
        whether they need a Marmin Business Profile ID we may not have for
        an external buyer). Same "fill in once confirmed" approach as
        _build_invoice_payload's own unmapped-optional-fields note."""
        default_vat_category = doc.custom_vat_category
        default_vat_rate = doc.taxes[0].rate if doc.taxes else 0
        default_exemption_label = doc.custom_vat_exemption_reason_code

        payload = {
            "profile_execution_id": MARMIN_PROFILE_EXECUTION_ID_STANDARD,
            "issue_date": str(doc.posting_date),
            "issue_time": get_issue_time(doc),
            "credit_note_type_code": get_invoice_type_code(doc),
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

        # document_number is mandatory (confirmed live: Marmin rejected a
        # credit note with no document_number at all with a 400 -
        # "Document number is mandatory when auto numbering is disabled").
        # Unlike the invoice payload, where document_number is just this
        # document's own name, a credit note's document_number is the
        # ORIGINAL invoice's Marmin-assigned document id - custom_document_id
        # on that Sales Invoice (the same field the webhook listener above
        # matches resource_id against), not this credit note's own docname
        # and not the "id" get_document_xml/get_document_pdf read out of a
        # submit response. Only available when return_against links to a
        # real Sales Invoice in this system that has actually been
        # submitted to Marmin already - throws with a clear reason for
        # either gap rather than sending an empty/wrong value and getting
        # another opaque 400 back.
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

    def _build_payment_means(self, doc):
        """Build payment_means by reusing Flick's own get_payment_means(doc)
        (json_einvoice.py) - the one real derivation from this invoice's
        Payments table -> Mode of Payment -> Accounts, instead of a second,
        parallel copy of that same lookup living here too. Whatever that
        function returns (it loops doc.payments and reads bank details off
        each row's Mode of Payment) is what this adapter reshapes into
        Marmin's payment_means entries - nothing here is invented.

        Real data always wins: if the invoice has a Payments row with a
        Mode of Payment that carries a valid code, that's what gets sent.
        MARMIN_DEFAULT_PAYMENT_MEANS_CODE only kicks in when
        get_payment_means(doc) comes back completely empty (no Payments
        row at all, or a Mode of Payment with no code configured) -
        confirmed necessary, not just theoretical, since Marmin rejects a
        submission outright (400, "At least one payment means is
        mandatory") when payment_means is an empty array. So this isn't a
        silent stand-in for real data that exists but wasn't read
        correctly - it only ever fires when there's genuinely nothing on
        the invoice to derive from.

        Still validates each code against MARMIN_APPROVED_PAYMENT_MEANS_CODES
        - that's a real constraint from Marmin's own docs (a different, and
        narrower, list than PEPPOL's, which get_payment_means itself doesn't
        restrict against), so a code that's fine for Flick but not Marmin
        still throws here with a clear message, instead of bouncing back as
        an opaque 400 from Marmin's side."""
        entries = []

        for pm in get_payment_means(doc):
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
                # card_account (54/55) and payment_mandate (49) aren't wired
                # up - get_payment_means only fills in placeholder card
                # details (a fake card number/network), and sending those to
                # Marmin isn't better than a clear error telling you this
                # combination isn't supported yet.
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
        apparently always dead code, never actually invoked (the only
        thing that ever called it, participant.py's update_flick_participant
        wrapper, had zero real callers of its own anywhere in the app - that
        file has since been removed).

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


# ---- webhook listener ----
# Everything below is the RECEIVING side of Marmin's webhook (see
# get_webhook_listener_url above for the SUBSCRIBING side, still
# dashboard-only). Confirmed against the real "Webhook Payload Format" and
# "Webhook Signature Verification" docs pages, pasted directly into this
# conversation.

# Header Marmin sends the webhook signature in - NOT actually confirmed
# against the "Webhook Signature Verification" docs page. That page's code
# sample only showed the verification function itself (HMAC-SHA256,
# base64, compared against a receivedSignature argument) - it didn't show
# where receivedSignature comes from on the real HTTP request. Using the
# same header name Marmin's own token endpoint already uses for its own
# HMAC signature (x-marmin-signature - see _fetch_token above) as a
# reasoned best guess, since it's their established convention for "an
# HMAC signature goes in this header" elsewhere in this same API - but
# this specific value is NOT verified for webhooks. If real deliveries
# get rejected (or, worse, silently accepted without a valid signature)
# once this is live, check the exact header name against that docs page
# and fix this constant rather than leaving it silently wrong.
MARMIN_WEBHOOK_SIGNATURE_HEADER = "x-marmin-signature"


def _verify_marmin_webhook_signature(raw_body, received_signature, webhook_secret):
    """HMAC-SHA256(key=webhook_secret, message=raw_body), base64-encoded -
    this is exactly Marmin's own verifyWebhookSignature function from
    their Webhook Signature Verification docs page, translated from the
    JS sample given there.

    raw_body must be the exact raw bytes of the request body, not
    re-serialized JSON - HMACs are byte-exact, so parsing the payload and
    re-encoding it before hashing would silently break verification
    against a real, unmodified delivery (different key order or
    whitespace produces a different signature even though the data is
    "the same")."""
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
    Web Application's Developer Dashboard > Webhooks config screen.

    Confirmed against the real docs pages pasted directly into this
    conversation:
    - Webhook Payload Format: {org_id, event_type, profile_id,
      resource_id, resource_url, event_timestamp, webhook_event_id}.
      Notably NOT shaped like Flick's payload, which embeds the new
      status directly - Marmin's is only a notification that SOMETHING
      changed on resource_id (Marmin's own invoice id, the same one
      get_document_xml/get_document_status/get_document_pdf all key off
      already), with no status field of its own. So this listener
      re-fetches the real current status itself via peppol-status-logs
      (same endpoint/derivation "Get Document Status" already uses)
      rather than trusting anything in the payload body about what
      actually changed.
    - Webhook Signature Verification: see _verify_marmin_webhook_signature
      above.

    NOT yet confirmed - fill in once you have the real docs page content:
    - MARMIN_WEBHOOK_SIGNATURE_HEADER's exact value (see its own comment
      above).
    - The exact success response body/status Marmin's "Expected Response"
      docs page wants, and what "Delivery & Retry Behavior" actually does
      on anything else - this returns a plain 200 + small JSON body for
      now, matching flick_webhook_listener's own convention, not checked
      against those two specific docs pages yet.
    """
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

    # profile_id is Marmin's Business Profile ID - the same value stored
    # in Participant ID on this company's E-Invoice Provider Settings row
    # (see get_participant_details above), so it's what identifies WHICH
    # row's Webhook Secret to check this delivery's signature against.
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
        # Reject rather than silently trust an unverifiable payload just
        # because its shape looks right - if this constant's header name
        # turns out to be wrong, every real delivery ends up here, which
        # is exactly the loud, checkable failure mode you want instead of
        # quietly accepting forged status updates.
        frappe.log_error(
            f"Signature check failed for Marmin webhook_event_id "
            f"{webhook_event_id} (profile_id {profile_id}) - header "
            f"checked: {MARMIN_WEBHOOK_SIGNATURE_HEADER}",
            "Marmin Webhook Signature Mismatch",
        )
        frappe.local.response["http_status_code"] = 401
        return {"received": False, "error": "signature verification failed"}

    # Find which local document this resource_id actually is FIRST - needed
    # to know whether it's a credit note (its Marmin id lives under
    # sales-credit-notes, not sales-invoices - see _document_resource_path)
    # before making the status-log call below, not after.
    sales_invoice_row = frappe.db.get_value(
        "Sales Invoice", {"custom_document_id": resource_id}, ["name", "is_return"], as_dict=True
    )
    # Marmin doesn't support Purchase Invoice submission yet (submit_invoice
    # above throws for anything but Sales Invoice) - checking here too
    # costs nothing and keeps this symmetric with flick_webhook_listener,
    # for whenever that changes. No credit-note concept for Purchase
    # Invoice here yet either, so it always reads as an invoice.
    purchase_invoice_name = frappe.db.get_value(
        "Purchase Invoice", {"custom_document_id": resource_id}, "name"
    )

    is_return = bool(sales_invoice_row and sales_invoice_row.is_return)
    resource_path = "sales-credit-notes" if is_return else "sales-invoices"

    # Signature verified - now find out what actually changed, since the
    # payload itself doesn't say.
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