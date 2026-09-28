"""this file contains the functions to send the purchase invoice."""
import frappe
import json
import requests
from frappe import _
from uae_erpgulf.uae_erpgulf.purchase_json  import send_invoice_json
from uae_erpgulf.uae_erpgulf.provider_settings import get_active_provider_settings
from uae_erpgulf.uae_erpgulf.providers import get_adapter
from uae_erpgulf.uae_erpgulf.attach import get_document_xml
from uae_erpgulf.uae_erpgulf.attach import get_document_pdf
from uae_erpgulf.uae_erpgulf.validation import success_log
def send_invoice_to_provider(doc, method=None):
    """On Purchase Invoice Submit and after JSON generation, send it"""

    try:
        settings = get_active_provider_settings(doc.company)
        adapter = get_adapter(settings)

        json_data = None
        if getattr(adapter, "USES_SHARED_INVOICE_JSON", True):
            
            files = frappe.get_all(
                "File",
                filters={
                    "attached_to_doctype": "Purchase Invoice",
                    "attached_to_name": doc.name,
                    "file_name": ["like", "%_uae_invoice.json"],
                },
                fields=["file_url", "file_name"],
            )
            json_file = files[0] if files else None

            if not json_file:
                frappe.throw(_("No JSON attachment found."))
            file_doc = frappe.get_doc("File", {"file_url": json_file.file_url})
            file_path = file_doc.get_full_path()

            with open(file_path, "r", encoding="utf-8") as f: # nosemgrep: frappe-security-file-traversal
                json_data = json.load(f)

        status_code, response_data = adapter.submit_invoice("Purchase Invoice", doc, json_data)

        
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

        frappe.msgprint(html, title="Simulated Incoming Invoice", wide=True)
        return status_code, response_data

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "E-Invoice Submit Error")
        
        frappe.throw(
            _("Error while sending invoice to the e-invoicing provider: {0}").format(str(e))
        )


from typing import Optional, Union
from frappe.model.document import Document
import time
@frappe.whitelist(allow_guest=False)
def generate_and_send_einvoice(doc: Union[Document, str], method: Optional[str] = None):
    """
    Store Success/Failed in custom_uae_einvoice_status
    """

    if isinstance(doc, str):
        doc = frappe.parse_json(doc)

    if isinstance(doc, dict):
        doc = frappe.get_doc(doc)
    if doc.doctype != "Purchase Invoice":
        return

    try:
        settings = get_active_provider_settings(doc.company)
        adapter = get_adapter(settings)

        
        if getattr(adapter, "USES_SHARED_INVOICE_JSON", True):
            json_response = send_invoice_json(doc.name)
            if not json_response:
                frappe.throw(_("Failed to generate eInvoice JSON"))

        status_code, response_data = send_invoice_to_provider(doc)
        if isinstance(response_data, dict):
            response_text = json.dumps(response_data, indent=4)
        else:
            response_text = str(response_data)

        invoice_status = "Not Submitted"
        reporting_status = None
        document_id = None

        if isinstance(response_data, dict):
            data = response_data.get("data", {})
            reporting_status = data.get("reporting_status") or response_data.get("reporting_status")
            document_id = data.get("id") or response_data.get("id")

        
        if status_code in (200, 201):
            if isinstance(response_data, dict):
                if response_data.get("status") in ["success", "processed", "accepted"] or document_id:
                    invoice_status = "Success"
            else:
                invoice_status = "Success"
        # Save status

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
                        fetch_fn("Purchase Invoice", doc.name)
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

        exchange_status = None

        if isinstance(response_data, dict):
            data = response_data.get("data", {})
            exchange_status = data.get("exchange_status")
        if status_code in (200, 201):
            settings = get_active_provider_settings(doc.company)

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
        # frappe.msgprint(
        #     _("Flick Response Stored. Status: {0}").format(invoice_status)
        # )

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
            doc = frappe.get_doc("Purchase Invoice", invoice)
            company_doc = frappe.get_doc("Company", doc.company)

            status = doc.custom_uae_einvoice_status

            # Skip already submitted invoices
            if status == "Success":
                skipped.append(invoice)
                continue

            # If invoice is Draft → Submit first
            if doc.docstatus == 0 and company_doc.custom_uae_einvoice_enabled == 1:
                doc.submit()

            # If invoice is Submitted → Send to FTA
            if doc.docstatus == 1 and company_doc.custom_uae_einvoice_enabled == 1:
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




@frappe.whitelist()
def get_document_status(invoice_name: str):
    """Fetch document status from this company's active provider and save
    the response in the Purchase Invoice."""
    try:
        purchase_invoice_doc = frappe.get_doc("Purchase Invoice", invoice_name)
        settings = get_active_provider_settings(purchase_invoice_doc.company)
        adapter = get_adapter(settings)

        result = adapter.get_document_status("Purchase Invoice", purchase_invoice_doc)
        if isinstance(result, dict) and "http_status" in result:
            http_status = result.get("http_status")
            body = result.get("response")
        else:
            http_status = None
            body = result

        purchase_invoice_doc.db_set(
            "custom_document_status_response",
            json.dumps(body)
        )

        reporting_status = result.get("reporting_status") if isinstance(result, dict) else None
        if not reporting_status and isinstance(body, dict):
            data = body.get("data", {})
            reporting_status = data.get("reporting_status") or body.get("reporting_status")
        if reporting_status:
            purchase_invoice_doc.db_set("custom_reporting_status", reporting_status)

        return {"http_status": http_status, "response": body}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "E-Invoice Document Status Error")
        frappe.throw(_("Failed to fetch document status: {0}").format(str(e)))