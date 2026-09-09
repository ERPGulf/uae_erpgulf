import frappe
import requests
import json
from frappe import _
from uae_erpgulf.uae_erpgulf.provider_settings import (
    get_settings_for_action,
    save_last_response,
)
from uae_erpgulf.uae_erpgulf.providers import get_adapter


@frappe.whitelist(allow_guest=True)# nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method
def flick_webhook_listener():
    """Listener for Flick API webhooks. Logs incoming data and updates invoice status."""
    try:

        raw_data = frappe.request.get_data(as_text=True)
        data = json.loads(raw_data)

        # 🔹 Extract top-level fields
        event_type = data.get("event")
        participant_id = data.get("participant_id")

        # 🔹 Extract nested data
        doc_data = data.get("data", {})

        document_id = doc_data.get("document_id")
        status = doc_data.get("status")
        exchange_status = doc_data.get("exchange_status")
        reporting_status = doc_data.get("reporting_status")
        invoice_number = doc_data.get("document_identifier")

        # ✅ Create Webhook Log Doc
        doc = frappe.get_doc({
            "doctype": "UAE E-Invoice Webhook Logs",
            "webhook_response": raw_data,
            "document_id": document_id,
            "participant_id": participant_id,
            "event_type": event_type,
            "reporting_status": reporting_status,
            "exchange_status": exchange_status,
            "invoice_number":invoice_number,
            "status": status
        })

        doc.insert(ignore_permissions=True)
        if document_id and reporting_status:

            # 🔹 Sales Invoice
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

            # 🔹 Purchase Invoice
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

        # frappe.db.commit()
        frappe.db.commit()

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
