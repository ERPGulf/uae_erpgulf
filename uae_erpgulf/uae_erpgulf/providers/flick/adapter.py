"""Flick Network L.L.C adapter.

Every Flick-specific detail (URL paths, header names, payload/response
shapes) lives here and nowhere else in the app. This is a straight move of
the logic that used to be spread across verify_token.py / test.py /
send_purchase.py / attach.py / webhook.py / participant.py / customer.py -
nothing about how it talks to Flick has changed, it's just now behind the
same interface every other adapter uses.
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
        access_token = response.json().get("access_token")

        if not access_token:
            frappe.throw(_("Access token not found in response"))

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

        payload = {"document": json_data}
        response = requests.post(url, headers=headers, json=payload, timeout=120)

        try:
            response_data = response.json()
        except Exception:
            response_data = response.text if doctype != "Purchase Invoice" else {}

        return response.status_code, response_data

    def get_document_status(self, doctype, doc):
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
        if not base_url:
            frappe.throw(_("Base URL is missing on E-Invoice Provider Settings"))

        url = f"{base_url}/v1/{participant_id}/documents/{document_id}"
        headers = self.get_auth_headers()
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            return response.json()

        return {"status": "error", "message": response.text}

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
    def register_webhook(self):
        settings = self.settings
        base_url = self.get_base_url()
        url = f"{base_url}/v1/webhooks/subscriptions"
        participant_id = settings.participant_id

        headers = self.get_auth_headers({"Content-Type": "application/json"})

        endpoint = frappe.utils.get_url(
            "/api/method/uae_erpgulf.uae_erpgulf.webhook.flick_webhook_listener"
        )
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
