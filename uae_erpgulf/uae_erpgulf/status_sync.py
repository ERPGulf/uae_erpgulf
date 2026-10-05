"""Common e-invoice status sync for every ASP."""

import json
import time
import frappe
from uae_erpgulf.uae_erpgulf.provider_settings import get_active_provider_settings
from uae_erpgulf.uae_erpgulf.providers import get_adapter

INVOICE_DOCTYPES = ("Sales Invoice", "Purchase Invoice")
DEFAULT_FINAL_STATUSES = ("reported", "rejected", "failed")
SYNC_LOOKBACK_DAYS = 7
SYNC_BATCH_SIZE = 50


def _flag(adapter, name, default):
    return getattr(adapter, name, default)


def _final_statuses(adapter):
    return tuple(s.lower() for s in _flag(adapter, "FINAL_REPORTING_STATUSES", DEFAULT_FINAL_STATUSES))


def _adapter_for(doc):
    return get_adapter(get_active_provider_settings(doc.company))


def attach_missing_documents(doctype, invoice_name):
    """Fetch only the XML / PDF this invoice doesn't have yet. attach.py
    logs failures to the Error Log; here they are swallowed (and their popup
    messages dropped) so a sync, poll or webhook is never interrupted."""
    from uae_erpgulf.uae_erpgulf.attach import get_document_pdf, get_document_xml

    current = frappe.db.get_value(
        doctype, invoice_name, ["custom_document_xml", "custom_document_pdf"], as_dict=True
    ) or {}

    for attached_field, fetch_fn in (
        ("custom_document_xml", get_document_xml),
        ("custom_document_pdf", get_document_pdf),
    ):
        if current.get(attached_field):
            continue
        messages_before = len(frappe.local.message_log)
        try:
            fetch_fn(doctype, invoice_name)
        except Exception:
            del frappe.local.message_log[messages_before:]


def refresh_invoice_status(doctype, invoice_name):
    """Same steps as the Get Status button: ask the adapter, store the
    response, set custom_reporting_status. Once reported, attach any missing
    XML / PDF. Returns the status (lower case) or None."""
    doc = frappe.get_doc(doctype, invoice_name)
    adapter = _adapter_for(doc)

    result = adapter.get_document_status(doctype, doc)
    if isinstance(result, dict) and "http_status" in result:
        body = result.get("response")
    else:
        body = result

    doc.db_set("custom_document_status_response", json.dumps(body, default=str), update_modified=False)

    status = result.get("reporting_status") if isinstance(result, dict) else None
    if not status:
        status = adapter.get_status_from_document_status(body)
    status = (status or "").strip().lower() or None

    if status and status != (doc.get("custom_reporting_status") or "").lower():
        doc.db_set("custom_reporting_status", status)

    if status == "reported" and _flag(adapter, "ATTACH_DOCUMENTS_IN_SYNC", True):
        attach_missing_documents(doctype, invoice_name)

    frappe.db.commit()  # nosemgrep: frappe-manual-commit
    return status


def enqueue_status_poll(doctype, invoice_name):
    """Call after a successful submit. Queues poll_invoice_status on the
    long queue, unless the adapter turned polling off."""
    try:
        doc = frappe.get_doc(doctype, invoice_name)
        adapter = _adapter_for(doc)
    except Exception:
        return
    if not _flag(adapter, "POLL_AFTER_SUBMIT", True) or not _flag(adapter, "STATUS_SYNC_ENABLED", True):
        return

    frappe.enqueue(
        "uae_erpgulf.uae_erpgulf.status_sync.poll_invoice_status",
        queue="long",
        doctype=doctype,
        invoice_name=invoice_name,
        attempts=_flag(adapter, "POLL_AFTER_SUBMIT_ATTEMPTS", 6),
        interval=_flag(adapter, "POLL_AFTER_SUBMIT_INTERVAL_SECONDS", 20),
        enqueue_after_commit=True,
    )


def poll_invoice_status(doctype, invoice_name, attempts=6, interval=20):
    """Background job: refresh every `interval` seconds until the status is
    final or the attempts run out. Whatever is left, the scheduler picks up."""
    for _i in range(int(attempts)):
        time.sleep(int(interval))
        try:
            if not frappe.db.get_value(doctype, invoice_name, "custom_document_id"):
                continue
            status = refresh_invoice_status(doctype, invoice_name)
            adapter = _adapter_for(frappe.get_doc(doctype, invoice_name))
            if status in _final_statuses(adapter):
                return
        except Exception:
            frappe.db.rollback()
            frappe.log_error(frappe.get_traceback(), f"E-Invoice Status Poll Error - {invoice_name}")
            return


def sync_pending_invoices():
    """Scheduled every 5 minutes (hooks.py). For every ASP: submitted
    invoices from the last SYNC_LOOKBACK_DAYS days that have a Document ID
    and are not final yet, or are still missing XML / PDF."""
    since = frappe.utils.add_days(frappe.utils.nowdate(), -SYNC_LOOKBACK_DAYS)

    for doctype in INVOICE_DOCTYPES:
        rows = frappe.get_all(
            doctype,
            filters={
                "docstatus": 1,
                "custom_document_id": ["is", "set"],
                "posting_date": [">=", since],
            },
            or_filters=[
                [doctype, "custom_reporting_status", "is", "not set"],
                [doctype, "custom_reporting_status", "not in", list(DEFAULT_FINAL_STATUSES)],
                [doctype, "custom_document_xml", "is", "not set"],
                [doctype, "custom_document_pdf", "is", "not set"],
            ],
            fields=["name", "custom_reporting_status", "custom_document_xml", "custom_document_pdf"],
            order_by="modified asc",
            limit=SYNC_BATCH_SIZE,
        )

        for row in rows:
            try:
                doc = frappe.get_doc(doctype, row.name)
                adapter = _adapter_for(doc)
                if not _flag(adapter, "STATUS_SYNC_ENABLED", True):
                    continue

                status = (row.custom_reporting_status or "").lower()
                if status in _final_statuses(adapter):
                    # Final already. Only a reported invoice can still be
                    # waiting for its XML / PDF; rejected / failed never get one.
                    if status != "reported":
                        continue
                    if _flag(adapter, "ATTACH_DOCUMENTS_IN_SYNC", True):
                        attach_missing_documents(doctype, row.name)
                        frappe.db.commit()  # nosemgrep: frappe-manual-commit
                        continue
                    # This adapter attaches files inside get_document_status.

                refresh_invoice_status(doctype, row.name)
            except Exception:
                frappe.db.rollback()
                frappe.log_error(frappe.get_traceback(), f"E-Invoice Status Sync Error - {row.name}")