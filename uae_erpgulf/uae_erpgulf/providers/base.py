"""Shared base class for provider adapters.

Every real ASP (Flick, Marmin, ...) gets its own adapter module under
providers/<name>/adapter.py, subclassing BaseAdapter. The shared app files
(test.py, send_purchase.py, webhook.py, ...) only ever call
adapter.<method>(...) - they never check a provider name themselves. All
the provider-specific detail (URL paths, header names, payload/response
shapes) lives inside that provider's own adapter file, nowhere else.

A method a given ASP doesn't support yet (usually because we don't have a
verified docs page for it) should raise a clear frappe.throw explaining
what's missing, not guess at a shape that hasn't been confirmed.
"""

import frappe


class BaseAdapter:
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

    def get_cached_token(self):
        return frappe.cache().get_value(self._cache_key())

    def set_cached_token(self, token, expires_in_sec=55 * 60):
        """Access tokens only ever live here (Redis, via frappe.cache()) -
        never written to a DocType field."""
        frappe.cache().set_value(self._cache_key(), token, expires_in_sec=expires_in_sec)

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

    def submit_invoice(self, doctype, doc, json_data):
        """Send one invoice. Must return (status_code, response_data)."""
        raise NotImplementedError

    def get_document_status(self, doctype, doc):
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
