""" this file contains the functions to send the sales invoice to the provider"""
import frappe
import json
import requests
import time
from frappe import _
from uae_erpgulf.uae_erpgulf.provider_settings import get_active_provider_settings
from uae_erpgulf.uae_erpgulf.providers import get_adapter
from uae_erpgulf.uae_erpgulf.attach import get_document_xml
from uae_erpgulf.uae_erpgulf.attach import get_document_pdf
from uae_erpgulf.uae_erpgulf.validation import success_log

def send_invoice_to_provider(doc, method=None):
    """ On Sales Invoice Submit and after JSON generation """

    try:
        settings = get_active_provider_settings(doc.company)
        adapter = get_adapter(settings)

        status_code, response_data = adapter.submit_invoice("Sales Invoice", doc)

        if isinstance(response_data, (dict, list)):
            pretty_response = json.dumps(response_data, indent=2)
        else:
            pretty_response = str(response_data)

        html = """
            <p><b>HTTP Status:</b> {status_code}</p>
            <pre style="white-space:pre-wrap;background:#f6f8fa;padding:12px;
                border-radius:6px;max-height:400px;overflow:auto;font-size:12px;">{response}</pre>
            """.format(
                status_code=status_code,
                response=frappe.utils.escape_html(pretty_response),
            )


        frappe.msgprint(html, title="E-Invoice Response", wide=True)

        return status_code, response_data
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "E-Invoice Submit Error")
        
        frappe.throw(
            _("Error while sending invoice to the e-invoicing provider: {0}").format(str(e))
        )



from typing import Optional, Union
from frappe.model.document import Document
@frappe.whitelist(allow_guest=False)
def generate_and_send_einvoice(doc: Union[Document, str], method: Optional[str] = None):
    """ Store Success/Failed in custom_uae_einvoice_status """
    if isinstance(doc, str):
        doc = frappe.parse_json(doc)

    if isinstance(doc, dict):
        doc = frappe.get_doc(doc)
    if doc.doctype != "Sales Invoice":
        return

    try:
        settings = get_active_provider_settings(doc.company)
        adapter = get_adapter(settings)

        status_code, response_data = send_invoice_to_provider(doc)
        if isinstance(response_data, dict):
            response_text = json.dumps(response_data, indent=4)
        else:
            response_text = str(response_data)

        parsed = adapter.parse_submit_response(status_code, response_data)
        document_id = parsed.get("document_id")
        reporting_status = parsed.get("reporting_status")
        exchange_status = parsed.get("exchange_status")
        invoice_status = "Success" if parsed.get("success") else "Not Submitted"

        doc.db_set("custom_submit_response", response_text)
        if status_code in (200, 201) and getattr(
            adapter, "AUTO_FETCH_DOCUMENTS_ON_SUBMIT", True
        ):
            retry_attempts = max(
                1, getattr(adapter, "DOCUMENT_FETCH_RETRY_ATTEMPTS", 1)
            )
            retry_delay_seconds = getattr(
                adapter, "DOCUMENT_FETCH_RETRY_DELAY_SECONDS", 0
            )
            for fetch_fn, file_label in (
                (get_document_xml, "XML"),
                (get_document_pdf, "PDF"),
            ):
                for attempt in range(1, retry_attempts + 1):
                    
                    message_log_length_before = len(frappe.local.message_log)
                    try:
                        fetch_fn("Sales Invoice", doc.name)
                        break
                    except Exception:
                        del frappe.local.message_log[message_log_length_before:]
                        if attempt == retry_attempts:
                            frappe.log_error(
                                frappe.get_traceback(),
                                f"E-Invoice {file_label} Fetch Error",
                            )
                        elif retry_delay_seconds:
                            time.sleep(retry_delay_seconds)
        doc.db_set("custom_uae_einvoice_status", invoice_status)
       
        if not reporting_status and invoice_status == "Success":
            reporting_status = "pending"
        if reporting_status:
            doc.db_set("custom_reporting_status", reporting_status)
        if document_id:
            doc.db_set("custom_document_id", document_id)
        frappe.db.commit()
        if status_code in (200, 201):
            success_log(
                title="UAE E-Invoice Submitted Successfully",
                document_id=document_id,
                participant_id=settings.participant_id,
                invoice_number=doc.name,
                reporting_status=reporting_status,
                exchange_status=exchange_status,
                status=invoice_status,
                submit_response=response_text,
            )

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "UAE eInvoice Submit Error")
        frappe.msgprint(
            _("E-Invoice processing failed: {0}").format(str(e))
        )


@frappe.whitelist()
def bulk_send_invoices(invoices: list | str):
    """Bulk send multiple invoices to FTA, with error handling and status tracking."""
    if isinstance(invoices, str):
        invoices = frappe.parse_json(invoices)

    success = []
    skipped = []
    failed = []

    for invoice in invoices:
        try:
            # Load documents
            doc = frappe.get_doc("Sales Invoice", invoice)
            company_doc = frappe.get_doc("Company", doc.company)

            status = doc.custom_uae_einvoice_status

            if status == "Success":
                skipped.append(invoice)
                continue

            if doc.docstatus == 0 and company_doc.custom_uae_einvoice_enabled == 1:
                doc.submit()
                success.append(invoice)

            elif doc.docstatus == 1 and company_doc.custom_uae_einvoice_enabled == 1:
                generate_and_send_einvoice(doc)
                success.append(invoice)

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), f"FTA Bulk Submission Error: {invoice}")
            failed.append(f"{invoice} : {str(e)}")

    return {
        "success": success,
        "skipped": skipped,
        "failed": failed
    }