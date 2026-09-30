"""webhook fetching"""
import frappe
from frappe import _
from uae_erpgulf.uae_erpgulf.provider_settings import (
    get_settings_for_action,
    save_last_response,
)
from uae_erpgulf.uae_erpgulf.providers import get_adapter

# Backward compatibility only: webhook subscriptions registered before the
# listener moved still POST to uae_erpgulf.uae_erpgulf.webhook.flick_webhook_listener.
# The real listener is providers/flick/adapter.py. Delete this import once
# every company has re-registered its webhook (Register Webhook button).
from uae_erpgulf.uae_erpgulf.providers.flick.adapter import flick_webhook_listener  # noqa: E402,F401


def update_webhook_logs():
    """Refreshes each enabled provider's webhook delivery log."""
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
def register_webhook(company: str = None, provider_settings: str = None):
    """Register (or re-register) the webhook subscription """
    settings = get_settings_for_action(company, provider_settings)
    result = get_adapter(settings).register_webhook()

    save_last_response(settings, "last_webhook_subscribe_response", result)

    return result


@frappe.whitelist()
def custom_get_subscription(company: str = None, provider_settings: str = None):
    """Get the current webhook subscription details for this provider"""
    settings = get_settings_for_action(company, provider_settings)
    result = get_adapter(settings).get_subscription()

    save_last_response(settings, "last_webhook_subscription_response", result)

    return result


@frappe.whitelist()
def get_webhook_deliveries(company: str = None, provider_settings: str = None):
    """Get the current webhook delivery logs for this provider"""
    settings = get_settings_for_action(company, provider_settings)
    result = get_adapter(settings).get_webhook_deliveries()

    save_last_response(settings, "last_webhook_logs_response", result)

    return result


# old Flick-named path, kept so anything still calling it keeps working
register_flick_webhook = register_webhook
