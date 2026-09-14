"""Flick Network L.L.C adapter.
Every Flick-specific detail (URL paths, header names, payload/response
shapes) lives here and nowhere else in the app. This is a straight move of
the logic that used to be spread across verify_token.py / test.py /
send_purchase.py / attach.py / webhook.py / customer.py - nothing about how
it talks to Flick has changed, it's just now behind the same interface
every other adapter uses.
(participant.py used to be listed here too - it only ever held a thin
update_flick_participant() wrapper with zero real callers anywhere in the
app, so it's been removed rather than migrated.)
"""

import json
import frappe
import requests
from frappe import _
from frappe.utils import now_datetime

from uae_erpgulf.uae_erpgulf.providers.base import BaseAdapter


class FlickAdapter(BaseAdapter):

    # ---- auth ----
    def get_auth_headers(self, extra=None):
        headers = dict(extra or {})
        settings = self.settings

        if settings.auth_type == "api_key":
            api_key = settings.get_password("api_key")
            if not api_key:
                frappe.throw(
                    _("API Key is missing on E-Invoice Provider Settings {0}.").format(settings.name)
                )
            headers["X-Flick-Auth-Key"] = api_key

        elif settings.auth_type == "oauth2":
            headers["Authorization"] = f"Bearer {self.get_valid_token()}"

        else:
            frappe.throw(
                _("Unsupported Auth Type '{0}' on E-Invoice Provider Settings {1}.").format(
                    settings.auth_type, settings.name
                )
            )

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

        url = f"{base_url}/v1/oauth/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        response = requests.post(url, headers={"Content-Type": "application/json"}, json=payload)
        response.raise_for_status()
        response_json = response.json()
        access_token = response_json.get("access_token")

        if not access_token:
            frappe.throw(_("Access token not found in response"))

        # expires_in (seconds) is the standard OAuth2 client_credentials
        # field (RFC 6749) - use it when Flick sends it, so the cached TTL
        # (and Token Expires At on the form) matches what Flick actually
        # issued instead of the base class's flat 55-minute assumption.
        expires_in = response_json.get("expires_in")
        if isinstance(expires_in, (int, float)) and expires_in > 0:
            self.set_cached_token(access_token, expires_in_sec=int(expires_in))
        else:
            self.set_cached_token(access_token)

        return access_token

    # ---- verify / participant ----
    def verify_auth(self):
        settings = self.settings
        base_url = self.get_base_url()

        if not base_url:
            frappe.throw(_("Please enter Base URL on E-Invoice Provider Settings."))

        try:
            headers = self.get_auth_headers()
            response = requests.get(f"{base_url}/v1/auth/verify", headers=headers)

            try:
                response_text = json.dumps(response.json())
            except Exception:
                response_text = response.text

            settings.db_set("last_test_status", "Passed" if response.ok else "Failed")
            settings.db_set("last_test_on", now_datetime())

            return {"status": "success" if response.ok else "error", "response": response_text}

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Flick Verify Error")
            settings.db_set("last_test_status", "Failed")
            settings.db_set("last_test_on", now_datetime())
            return {"status": "error", "message": str(e)}

    def get_participant_details(self):
        settings = self.settings
        base_url = self.get_base_url()

        if not base_url:
            frappe.throw(_("Please enter Base URL on E-Invoice Provider Settings."))

        participant_id = settings.participant_id
        if not participant_id:
            frappe.throw(_("Participant ID is missing on E-Invoice Provider Settings"))

        headers = self.get_auth_headers()
        response = requests.get(f"{base_url}/v1/participants/{participant_id}", headers=headers)

        return {"status": "success", "response": response.json()}

    def lookup_peppol_id(self, peppol_id):
        base_url = self.get_base_url()
        url = f"{base_url}/v1/peppol/lookup/{peppol_id}"
        headers = self.get_auth_headers()

        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()

        frappe.throw(f"API Error: {response.text}")

    def update_participant(self, company_doc):
        settings = self.settings
        base_url = self.get_base_url()
        participant_id = settings.participant_id

        url = f"{base_url}/v1/participants/{participant_id}"
        headers = self.get_auth_headers({"Content-Type": "application/json"})

        payload = {
            "trade_name": company_doc.company_name,
            "legal_name": company_doc.company_name,
            "peppol_id": company_doc.custom_peppol_id,
            "street_address": company_doc.custom_street_address,
            "additional_street_address": company_doc.custom_additional_street,
            "additional_address_lines": company_doc.custom_additional_address,
            "city_address": company_doc.custom_city,
            "postal_zone": company_doc.custom_postal_code,
            "emirates_code": company_doc.custom_emirate_code,
            "country_code": company_doc.custom_country_code or "AE",
            "identifiers": [{"scheme_id": "AE:TL", "value": company_doc.tax_id}],
            "contact_name": company_doc.custom_contact_name,
            "contact_telephone": company_doc.custom_contact_phone,
            "contact_email": company_doc.custom_contact_email,
            "fz_beneficiary_id": company_doc.custom_fz_id,
        }

        try:
            response = requests.put(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            frappe.log_error(frappe.get_traceback(), "Flick Participant Update Error")
            return {
                "status": "error",
                "message": str(e),
                "response": getattr(e.response, "text", ""),
            }

    # ---- invoices ----
    def submit_invoice(self, doctype, doc, json_data):
        settings = self.settings
        participant_id = settings.participant_id
        if not participant_id:
            frappe.throw(_("Participant ID is missing on E-Invoice Provider Settings"))

        base_url = self.get_base_url()
        headers = self.get_auth_headers({"Content-Type": "application/json"})

        if doctype == "Purchase Invoice":
            url = f"{base_url}/v1/{participant_id}/simulate/incoming"
        else:
            url = f"{base_url}/v1/{participant_id}/documents"

        # Flick keeps ONLY its existing "<invoice>_uae_invoice.json" file
        # (save_and_attach_invoice_json in json_einvoice.py, already saved
        # before this ever runs) - no second file here. Every other ASP
        # (Marmin now, and any of the ~34 more that get their own adapter
        # later) calls self.save_outgoing_payload(doc, payload) instead,
        # since none of them already have a docs-verified JSON file of
        # their own the way Flick does.
        payload = {"document": json_data}

        response = requests.post(url, headers=headers, json=payload, timeout=120)

        try:
            response_data = response.json()
        except Exception:
            response_data = response.text if doctype != "Purchase Invoice" else {}

        return response.status_code, response_data

    def get_document_status(self, doctype, doc):
        """Return shape: always {"http_status": <int>, "response": <body>},
        success or failure - matches Marmin's adapter (see its own
        get_document_status docstring for why: so a failure here shows up
        in the "Get Document Status" dialog with its real HTTP status
        instead of escaping as Frappe's own generic red error box)."""
        settings = self.settings
        participant_id = settings.participant_id
        if not participant_id:
            frappe.throw(_("Participant ID is missing on E-Invoice Provider Settings"))

        if not doc.custom_submit_response:
            frappe.throw(_("Submit response not found in Invoice"))

        response_data = json.loads(doc.custom_submit_response)
        submit_data = response_data.get("data", {})
        document_id = submit_data.get("id")
        # Flick's own submit response carries a second identifier alongside
        # its internal id - document_identifier, which is just this
        # invoice's own name (doc.name). Falling back to doc.name here in
        # case an older submit response predates that field being saved.
        document_identifier = submit_data.get("document_identifier") or doc.name
        if not document_id:
            frappe.throw(_("Document ID not found in submit response"))

        base_url = self.get_base_url()
        if not base_url:
            frappe.throw(_("Base URL is missing on E-Invoice Provider Settings"))

        headers = self.get_auth_headers()

        # Primary call - the same "documents/{id}" path this adapter has
        # always used.
        url = f"{base_url}/v1/{participant_id}/documents/{document_id}"
        response = requests.get(url, headers=headers)

        if response.status_code != 200:
            return {"http_status": response.status_code, "response": response.text}

        try:
            data = response.json()
        except Exception:
            return {"http_status": response.status_code, "response": response.text}

    
        if isinstance(data, list) and not data and document_identifier:
            alt_url = f"{base_url}/v1/{participant_id}/documents"
            alt_response = requests.get(
                alt_url,
                headers=headers,
                params={"document_identifier": document_identifier},
            )
            if alt_response.status_code == 200:
                try:
                    alt_data = alt_response.json()
                except Exception:
                    alt_data = None
                if alt_data:
                    return {"http_status": alt_response.status_code, "response": alt_data}

        return {"http_status": response.status_code, "response": data}

    def get_document_xml(self, doctype, doc):
        settings = self.settings
        participant_id = settings.participant_id
        if not participant_id:
            frappe.throw(_("Participant ID is missing on E-Invoice Provider Settings"))
        if not doc.custom_submit_response:
            frappe.throw(_("Submit response not found in Invoice"))

        response_data = json.loads(doc.custom_submit_response)
        document_id = response_data.get("data", {}).get("id")
        if not document_id:
            frappe.throw(_("Document ID not found in submit response"))

        base_url = self.get_base_url()
        url = f"{base_url}/v1/{participant_id}/documents/{document_id}/xml"
        headers = self.get_auth_headers()
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            return response.text

        frappe.throw(_("API Error: {0}").format(response.text))

    def get_document_pdf(self, doctype, doc):
        settings = self.settings
        participant_id = settings.participant_id
        if not participant_id:
            frappe.throw(_("Participant ID is missing on E-Invoice Provider Settings"))
        if not doc.custom_submit_response:
            frappe.throw(_("Submit response not found in Invoice"))

        response_data = json.loads(doc.custom_submit_response)
        document_id = response_data.get("data", {}).get("id")
        if not document_id:
            frappe.throw(_("Document ID not found in submit response"))

        base_url = self.get_base_url()
        url = f"{base_url}/v1/{participant_id}/documents/{document_id}/pdf"
        headers = self.get_auth_headers()
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            return response.content

        frappe.throw(_("API Error: {0}").format(response.text))

    # ---- webhook ----
    def get_webhook_listener_url(self):
        """URL for flick_webhook_listener below - the one function in this
        file that genuinely can't be generic (it parses Flick's own webhook
        JSON shape directly), used both by register_webhook() here and by
        e_invoice_provider_settings.py's set_webhook_url() to fill in the
        Webhook URL field without that shared file needing to know Flick's
        URL itself."""
        return frappe.utils.get_url(
            "/api/method/uae_erpgulf.uae_erpgulf.providers.flick.adapter.flick_webhook_listener"
        )

    def register_webhook(self):
        settings = self.settings
        base_url = self.get_base_url()
        url = f"{base_url}/v1/webhooks/subscriptions"
        participant_id = settings.participant_id

        headers = self.get_auth_headers({"Content-Type": "application/json"})

        endpoint = self.get_webhook_listener_url()
        payload = {
            "name": "ERPNext Webhook",
            "endpoint": endpoint,
            "event_types": [
                "document.received",
                "document.exchange.delivered",
                "document.exchange.failed",
                "document.reporting.reported",
                "document.reporting.failed",
                "document.completed",
                "document.failed",
            ],
            "participant_ids": [participant_id],
        }

        response = requests.post(url, headers=headers, json=payload)

        try:
            response_data = response.json()
        except Exception:
            response_data = {"raw_response": response.text}

        if response_data.get("data") and response_data["data"].get("uuid"):
            settings.webhook_uuid = response_data["data"]["uuid"]
        if response_data.get("data") and response_data["data"].get("secret"):
            settings.webhook_secret = response_data["data"]["secret"]
        settings.save(ignore_permissions=True)

        return response_data

    def get_subscription(self):
        settings = self.settings
        base_url = self.get_base_url()
        uuid = settings.webhook_uuid

        if not uuid:
            frappe.throw(_("Webhook UUID not found. Please create subscription first."))

        url = f"{base_url}/v1/webhooks/subscriptions/{uuid}"
        headers = self.get_auth_headers()
        response = requests.get(url, headers=headers)

        try:
            return response.json()
        except Exception:
            return {"raw_response": response.text}

    def get_webhook_deliveries(self):
        settings = self.settings
        base_url = self.get_base_url()
        uuid = settings.webhook_uuid

        url = f"{base_url}/v1/webhooks/subscriptions/{uuid}/deliveries"
        headers = self.get_auth_headers()
        response = requests.get(url, headers=headers)

        try:
            return response.json()
        except Exception:
            return {"raw_response": response.text}


# ---- inbound webhook listener ----
# Moved here from webhook.py (was uae_erpgulf.uae_erpgulf.webhook.
# flick_webhook_listener - get_webhook_listener_url() above and
# e_invoice_provider_settings.py's set_webhook_url() both point at the new
# dotted path now). Everything else that used to live in webhook.py stayed
# there because it's genuinely generic (calls get_adapter(settings).
# register_webhook() etc.) - this is the one function that can't be, since
# it's the endpoint Flick's own server posts a Flick-shaped JSON body to,
# not something this app calls out to Flick. A future ASP with its own
# webhook API needs its own listener function shaped around its own
# payload, the same way this one is shaped around Flick's.
@frappe.whitelist(allow_guest=True)  # nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method
def flick_webhook_listener():
    """Listener for Flick API webhooks. Logs incoming data and updates invoice status."""
    try:

        raw_data = frappe.request.get_data(as_text=True)
        data = json.loads(raw_data)

        # Extract top-level fields
        event_type = data.get("event")
        participant_id = data.get("participant_id")

        # Extract nested data
        doc_data = data.get("data", {})

        document_id = doc_data.get("document_id")
        status = doc_data.get("status")
        exchange_status = doc_data.get("exchange_status")
        reporting_status = doc_data.get("reporting_status")
        invoice_number = doc_data.get("document_identifier")

        # Create Webhook Log Doc
        doc = frappe.get_doc({
            "doctype": "UAE E-Invoice Webhook Logs",
            "webhook_response": raw_data,
            "document_id": document_id,
            "participant_id": participant_id,
            "event_type": event_type,
            "reporting_status": reporting_status,
            "exchange_status": exchange_status,
            "invoice_number": invoice_number,
            "status": status
        })

        doc.insert(ignore_permissions=True)
        if document_id and reporting_status:

            # Sales Invoice
            sales_invoice = frappe.db.get_value(
                "Sales Invoice",
                {"custom_document_id": document_id},
                "name"
            )

            if sales_invoice:
                frappe.db.set_value(
                    "Sales Invoice",
                    sales_invoice,
                    "custom_reporting_status",
                    reporting_status
                )

            # Purchase Invoice
            purchase_invoice = frappe.db.get_value(
                "Purchase Invoice",
                {"custom_document_id": document_id},
                "name"
            )

            if purchase_invoice:
                frappe.db.set_value(
                    "Purchase Invoice",
                    purchase_invoice,
                    "custom_reporting_status",
                    reporting_status
                )

        frappe.db.commit()  # nosemgrep: frappe-manual-commit

        return {
            "acknowledged": True,
            "processed": True
        }

    except Exception:
        frappe.log_error(
            title="Webhook Processing Error",
            message=frappe.get_traceback()
        )
        return {
            "acknowledged": False,
            "processed": False
        }