"""Shared base class for provider adapters."""

from datetime import timedelta
import frappe
DEFAULT_TOKEN_TTL_SEC = 55 * 60


class BaseAdapter:
   
    AUTO_FETCH_DOCUMENTS_ON_SUBMIT = True

    def __init__(self, settings):
        """settings: the active E-Invoice Provider Settings doc for one
        company. Every adapter method reads whatever it needs off this."""
        self.settings = settings

    # ---- shared helpers (every adapter gets these for free) ----
    def get_base_url(self):
        """Base URL Override wins only if someone deliberately set it.
        Otherwise the provider's normal Base URL."""
        return self.settings.base_url_override or self.settings.base_url

    def _cache_key(self):
        return f"uae_einvoice_token:{self.settings.name}"

    def _token_expiry_cache_key(self):
        return f"uae_einvoice_token_expiry:{self.settings.name}"

    def get_cached_token(self):
        return frappe.cache().get_value(self._cache_key())

    def set_cached_token(self, token, expires_in_sec=DEFAULT_TOKEN_TTL_SEC):
        """Access tokens only ever live here (Redis, via frappe.cache())"""
        frappe.cache().set_value(self._cache_key(), token, expires_in_sec=expires_in_sec)
        expiry = frappe.utils.now_datetime() + timedelta(seconds=expires_in_sec)
        frappe.cache().set_value(
            self._token_expiry_cache_key(), expiry.isoformat(), expires_in_sec=expires_in_sec
        )

    def get_token_expiry(self):
        """Best-effort expiry of whatever token is currently cached, for
        display only. """
        raw = frappe.cache().get_value(self._token_expiry_cache_key())
        return frappe.utils.get_datetime(raw) if raw else None

    def save_outgoing_payload(self, doc, payload):
        """Attach the exact JSON body this adapter is about to send """
        provider_slug = self.__class__.__name__.replace("Adapter", "").lower() or "provider"
        file_name = f"{doc.name}_{provider_slug}_payload.json"

        old_files = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": doc.doctype,
                "attached_to_name": doc.name,
                "file_name": file_name,
            },
            fields=["name"],
        )
        for f in old_files:
            frappe.delete_doc("File", f.name, force=1, ignore_permissions=True)

        file_doc = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": file_name,
                "is_private": 1,
                "content": frappe.as_json(payload, indent=2),
                "attached_to_doctype": doc.doctype,
                "attached_to_name": doc.name,
            }
        )
        file_doc.insert(ignore_permissions=True)
        frappe.db.commit()  # nosemgrep: frappe-manual-commit

    def get_valid_token(self):
        """Return a cached OAuth2 token, refreshing via _fetch_token() if
        it's missing or expired. Only meaningful for a provider/row using
        OAuth2 - subclasses implement _fetch_token()."""
        token = self.get_cached_token()
        if token:
            return token
        return self._fetch_token()

    def _fetch_token(self):
        raise NotImplementedError

    # ---- methods every adapter should implement ----
    def get_auth_headers(self, extra=None):
        raise NotImplementedError

    def verify_auth(self):
        raise NotImplementedError

    def get_participant_details(self):
        raise NotImplementedError

    def lookup_peppol_id(self, peppol_id):
        raise NotImplementedError

    def update_participant(self, company_doc):
        raise NotImplementedError

    def submit_invoice(self, doctype, doc, json_data=None):
        """Build this ASP's own payload for doc and send it"""
        raise NotImplementedError

    def parse_submit_response(self, status_code, response_data):
        """Pull the fields the shared submit flow stores on the invoice out
        of submit_invoice()'s response. Returns a dict with document_id,
        reporting_status, exchange_status and success (bool)."""
        body = response_data if isinstance(response_data, dict) else {}
        data = body.get("data") if isinstance(body.get("data"), dict) else {}

        document_id = data.get("id") or body.get("id")
        reporting_status = data.get("reporting_status") or body.get("reporting_status")
        exchange_status = data.get("exchange_status") or body.get("exchange_status")

        success = False
        if status_code in (200, 201):
            if isinstance(response_data, dict):
                success = body.get("status") in ("success", "processed", "accepted") or bool(document_id)
            else:
                success = True

        return {
            "document_id": document_id,
            "reporting_status": reporting_status,
            "exchange_status": exchange_status,
            "success": success,
        }

    def get_status_from_document_status(self, body):
        """reporting_status out of a get_document_status() "response" body,
        for the shared "Get Document Status" buttons. Override if needed."""
        if not isinstance(body, dict):
            return None
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        return data.get("reporting_status") or body.get("reporting_status")

    def get_document_status(self, doctype, doc):
        """Should return {"http_status": <int>, "response": <body>}."""
        raise NotImplementedError

    def get_document_xml(self, doctype, doc):
        raise NotImplementedError

    def get_document_pdf(self, doctype, doc):
        raise NotImplementedError

    def register_webhook(self):
        raise NotImplementedError

    def get_subscription(self):
        raise NotImplementedError

    def get_webhook_deliveries(self):
        raise NotImplementedError

    def parse_incoming_invoice(self, invoice_json):
        """Turn this ASP's incoming (received) invoice JSON into one common
        shape, so the shared "Get FTA Incoming Invoice" import never has to
        know any provider's field names. Must return:

        {
            "supplier_name": str, "vat_number": str,
            "posting_date": str, "due_date": str, "currency": str,
            "document_id": str, "conversion_rate": float or None,
            "payment_means_code": str or None,
            "lines": [{"name", "description", "qty", "uom", "rate",
                       "amount", "vat_rate"}],
        }
        """
        raise NotImplementedError

    def get_webhook_listener_url(self):
        """The URL this ASP's own server should call to deliver webhook"""
        return None