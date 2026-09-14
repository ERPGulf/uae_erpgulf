import frappe
from frappe import _
from uae_erpgulf.uae_erpgulf.provider_settings import (
    get_settings_for_action,
    save_last_response,
)
from uae_erpgulf.uae_erpgulf.providers import get_adapter
from uae_erpgulf.uae_erpgulf.providers.flick.adapter import (
    flick_webhook_listener as _flick_webhook_listener,
)

# The real flick_webhook_listener used to live here - it's been moved to
# providers/flick/adapter.py (see get_webhook_listener_url() there), since
# it's the one function in this file that genuinely can't be generic: it
# parses Flick's own webhook JSON shape directly, rather than calling
# get_adapter(settings).<method>() the way everything below still does.
# Everything else in this file stays here because it IS truly ASP-agnostic.


@frappe.whitelist(allow_guest=True)  # nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method
def flick_webhook_listener():
    """Backward-compatible alias, kept at the OLD path this function used
    to live at (uae_erpgulf.uae_erpgulf.webhook.flick_webhook_listener) -
    just delegates to the real one, now in providers/flick/adapter.py.

    This exists because moving the function's module changed its
    whitelisted method path, and Flick's OWN webhook subscription (set up
    on their servers via "Subscribe Webhook") remembers whatever URL was
    current when it was registered - which may well be this old path, if
    the webhook hasn't been explicitly re-subscribed since the move.
    Without this alias, Flick keeps POSTing to a URL that no longer
    resolves to anything, and every delivery just 404s silently - no
    error anywhere in this app to notice, since the request never reaches
    it at all. This is very likely why webhook status updates stopped
    working after that refactor: not a logic bug in the listener itself,
    a moved endpoint nobody told Flick about.

    Keeping this alias means it doesn't matter which URL Flick currently
    has on file - old or new both work identically. Safe to remove only
    once you've confirmed (via "Get Subscription" on the Provider
    Settings row, or by re-subscribing) that Flick is actually POSTing to
    the new providers.flick.adapter path."""
    return _flick_webhook_listener()


def update_webhook_logs():
    """Scheduler poll (see hooks.py cron). Refreshes each enabled provider's
    webhook delivery log. NOTE: this only refreshes the log - it doesn't yet
    reconcile invoice status from what's polled, so the webhook listener
    above is still the only path that updates invoice status today. Making
    the poll a real fallback (not just a log refresh) is tracked as a
    follow-up in multi-asp-migration-plan.md, not done in this pass."""
    rows = frappe.get_all(
        "E-Invoice Provider Settings",
        filters={"enabled": 1, "webhook_uuid": ["is", "set"]},
        fields=["name", "company"],
    )

    for row in rows:
        try:
            get_webhook_deliveries(row.company)
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Webhook Log Update Failed - {row.company}"
            )

@frappe.whitelist(allow_guest=False)
def register_flick_webhook(company: str = None, provider_settings: str = None):
    """Register (or re-register) the webhook subscription for a specific
    row when one is given (that's what the Provider Settings form's own
    button passes), otherwise the active enabled row for the given company
    (older Company-button callers). Despite the name (kept for backward
    compatibility), this now works for any provider whose adapter
    implements register_webhook() - today that's Flick only; Marmin's is a
    documented "not implemented yet" stub until we have its webhook docs
    page.

    Saves a REDACTED copy of the response on Last Webhook Subscribe
    Response - this response contains the actual webhook secret (already
    saved properly in the Webhook Secret password field by the adapter),
    so it gets blanked out here before anything touches a plain-text field.
    """
    settings = get_settings_for_action(company, provider_settings)
    result = get_adapter(settings).register_webhook()

    save_last_response(settings, "last_webhook_subscribe_response", result)

    return result


@frappe.whitelist()
def custom_get_subscription(company: str = None, provider_settings: str = None):
    settings = get_settings_for_action(company, provider_settings)
    result = get_adapter(settings).get_subscription()

    save_last_response(settings, "last_webhook_subscription_response", result)

    return result


@frappe.whitelist()
def get_webhook_deliveries(company: str = None, provider_settings: str = None):
    settings = get_settings_for_action(company, provider_settings)
    result = get_adapter(settings).get_webhook_deliveries()

    save_last_response(settings, "last_webhook_logs_response", result)

    return result