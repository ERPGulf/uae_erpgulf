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

from datetime import timedelta

import frappe

# Fallback token TTL when an ASP's token response doesn't tell us how long
# the token actually lives (Flick's and Marmin's _fetch_token() both try to
# read a real expires_in from the response first - this is only used when
# that's absent, so an old guess doesn't silently stay wrong forever once a
# real value is available).
DEFAULT_TOKEN_TTL_SEC = 55 * 60


class BaseAdapter:
    # Whether this ASP's submit_invoice() actually needs the shared
    # PEPPOL/UBL-style "<invoice>_uae_invoice.json" file (built once, the
    # same way, for every provider by save_and_attach_invoice_json in
    # json_einvoice.py) as its json_data argument. True by default so
    # nothing changes for an adapter that doesn't override it - Flick
    # relies on this file (it's Flick's actual request body). An adapter
    # that builds its own payload straight from the Sales Invoice doc
    # instead (Marmin does) should set this to False, so test.py skips
    # generating/attaching a file that would just be ignored.
    USES_SHARED_INVOICE_JSON = True

    # Whether, right after a successful submit_invoice() (status 200/201),
    # the shared flow (generate_and_send_einvoice in test.py) should
    # automatically call get_document_xml()/get_document_pdf() and attach
    # whatever comes back. True by default - Flick's XML/PDF are generated
    # synchronously by the time submit_invoice() returns, so fetching them
    # immediately always works. An ASP whose document generation is async
    # (Marmin: XML is generated some time after acceptance, and it has no
    # PDF endpoint at all yet) should set this False, so a "not generated
    # yet" response from the ASP's own server isn't logged as an Error Log
    # entry on every single successful submission - that ASP's adapter
    # methods are still there and correct, just meant to be called later
    # (e.g. from a "Get Document Status"/"Get XML" button) instead of
    # automatically right after submit.
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
        """Access tokens only ever live here (Redis, via frappe.cache()) -
        never written to a DocType field. Also stashes the moment this
        token expires under its own Redis key, at the same TTL, purely so
        get_token_expiry() can show "Token Expires At" on Provider Settings
        for visibility - Redis's own TTL on the token itself is still what
        actually drives refreshing (get_valid_token() below), regardless of
        whether anything ever reads this second key."""
        frappe.cache().set_value(self._cache_key(), token, expires_in_sec=expires_in_sec)
        expiry = frappe.utils.now_datetime() + timedelta(seconds=expires_in_sec)
        frappe.cache().set_value(
            self._token_expiry_cache_key(), expiry.isoformat(), expires_in_sec=expires_in_sec
        )

    def get_token_expiry(self):
        """Best-effort expiry of whatever token is currently cached, for
        display only. Returns None if nothing is cached right now (never
        fetched yet, or already expired) - callers should treat that as
        "unknown", not an error."""
        raw = frappe.cache().get_value(self._token_expiry_cache_key())
        return frappe.utils.get_datetime(raw) if raw else None

    def save_outgoing_payload(self, doc, payload):
        """Attach the exact JSON body this adapter is about to send to its
        ASP as a File on the invoice - named "<invoice>_<provider>_payload.json"
        (e.g. "ACC-SINV-2026-00203_marmin_payload.json"), so whichever
        provider is active, you can always see exactly what was sent from
        the invoice's own Attachments, the same way the Flick-shaped
        "<invoice>_uae_invoice.json" file already works
        (save_and_attach_invoice_json in json_einvoice.py) - just one file
        per provider instead of one shared file every provider re-guesses
        from.

        Only replaces THIS provider's own previous payload file (matched by
        exact file name), so it never touches the Flick-shaped file or
        another provider's payload file if you switch providers on the same
        invoice later.

        Call this right before the actual request, in submit_invoice(), so
        a file is always saved even if the request itself then fails - that
        way a 400 response is just as debuggable as a success.
        """
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