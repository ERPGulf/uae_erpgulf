

import frappe
import json
import requests
from frappe import _
from uae_erpgulf.uae_erpgulf.json_einvoice import send_invoice_json
from uae_erpgulf.uae_erpgulf.provider_settings import get_active_provider_settings
from uae_erpgulf.uae_erpgulf.providers import get_adapter
from uae_erpgulf.uae_erpgulf.attach import get_document_xml
from uae_erpgulf.uae_erpgulf.attach import get_document_pdf
from uae_erpgulf.uae_erpgulf.validation import success_log

def send_invoice_to_provider(doc, method=None):
    """
    On Sales Invoice Submit and after JSON generation, send it to whichever
    ASP this company's active E-Invoice Provider Settings row points at.
    Which URL/payload shape that means is entirely the adapter's business -
    this function never checks a provider name.
    """

    try:
        files = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": "Sales Invoice",
                "attached_to_name": doc.name
            },
            fields=["file_url", "file_name"]
        )
        json_file = None
        for f in files:
            if f.file_name.lower().endswith(".json"):
                json_file = f
                break

        if not json_file:
            frappe.throw(_("No JSON attachment found."))
        file_doc = frappe.get_doc("File", {"file_url": json_file.file_url})
        file_path = file_doc.get_full_path()

        with open(file_path, "r", encoding="utf-8") as f: # nosemgrep: frappe-security-file-traversal
            json_data = json.load(f)

        settings = get_active_provider_settings(doc.company)
        adapter = get_adapter(settings)

        status_code, response_data = adapter.submit_invoice("Sales Invoice", doc, json_data)

        data = response_data.get("data", {}) if isinstance(response_data, dict) else {}
        message = response_data.get("message", "-") if isinstance(response_data, dict) else "-"
        api_status = response_data.get("status", "-") if isinstance(response_data, dict) else "-"

        html = """
            <table border="1" cellpadding="8" cellspacing="0"
                style="border-collapse:collapse;width:100%;font-size:13px;">
                <thead>
                    <tr style="background-color:#f0f4f7;">
                        <th style="padding:8px 12px;text-align:left;border:1px solid #d1d8dd;">Field</th>
                        <th style="padding:8px 12px;text-align:left;border:1px solid #d1d8dd;">Value</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td style="padding:8px 12px;border:1px solid #d1d8dd;"><b>API Status</b></td>
                        <td style="padding:8px 12px;border:1px solid #d1d8dd;">{api_status}</td>
                    </tr>
                    <tr style="background-color:#f9f9f9;">
                        <td style="padding:8px 12px;border:1px solid #d1d8dd;"><b>Message</b></td>
                        <td style="padding:8px 12px;border:1px solid #d1d8dd;">{message}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 12px;border:1px solid #d1d8dd;"><b>Document ID</b></td>
                        <td style="padding:8px 12px;border:1px solid #d1d8dd;">{doc_id}</td>
                    </tr>
                    <tr style="background-color:#f9f9f9;">
                        <td style="padding:8px 12px;border:1px solid #d1d8dd;"><b>Processing Status</b></td>
                        <td style="padding:8px 12px;border:1px solid #d1d8dd;">{proc_status}</td>
                    </tr>
                    <tr>
                        <td style="padding:8px 12px;border:1px solid #d1d8dd;"><b>Reporting Status</b></td>
                        <td style="padding:8px 12px;border:1px solid #d1d8dd;">{rep_status}</td>
                    </tr>
                </tbody>
            </table>
            """.format(
                api_status=api_status,
                message=message,
                doc_id=data.get('id', '-'),
                proc_status=data.get('status', '-'),
                rep_status=data.get('reporting_status', '-')
            )
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
    except Exception:
        frappe.log_error(frappe.get_traceback(), "E-Invoice Submit Error")
        frappe.throw(_("Error while sending invoice to the e-invoicing provider."))



from typing import Optional, Union
from frappe.model.document import Document
@frappe.whitelist(allow_guest=False)
def generate_and_send_einvoice(doc: Union[Document, str], method: Optional[str] = None):
    """
    Store Success/Failed in custom_uae_einvoice_status
    """
    if isinstance(doc, str):
        doc = frappe.parse_json(doc)

    if isinstance(doc, dict):
        doc = frappe.get_doc(doc)
    if doc.doctype != "Sales Invoice":
        return

    try:
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

        # Extract reporting_status safely
        if isinstance(response_data, dict):
            data = response_data.get("data", {})
            reporting_status = data.get("reporting_status")
            document_id = data.get("id")

        # 200 = Flick's success code, 201 Created = Marmin's - both mean
        # "accepted", so both count here.
        if status_code in (200, 201):
            if isinstance(response_data, dict):
                if response_data.get("status") in ["success", "processed", "accepted"] or document_id:
                    invoice_status = "Success"
            else:
                invoice_status = "Success"
        # Save

        doc.db_set("custom_submit_response", response_text)
        if status_code in (200, 201):
            # XML/PDF fetch isn't implemented for every provider yet (e.g.
            # Marmin) - don't let that turn a real submit success into a
            # logged failure below.
            try:
                get_document_xml("Sales Invoice", doc.name)
                get_document_pdf("Sales Invoice", doc.name)
            except Exception:
                frappe.log_error(frappe.get_traceback(), "E-Invoice XML/PDF Fetch Error")
        doc.db_set("custom_uae_einvoice_status", invoice_status)
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

    except Exception:
        frappe.log_error(frappe.get_traceback(), "UAE eInvoice Submit Error")

        frappe.msgprint(
            _("E-Invoice processing failed. Check Submit Response field.")
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

            # Skip already submitted invoices
            if status == "Success":
                skipped.append(invoice)
                continue

            # If invoice is Draft → Submit first
            if doc.docstatus == 0 and company_doc.custom_uae_einvoice_enabled == 1:
                doc.submit()
                success.append(invoice)

            # If invoice is Submitted → Send to FTA
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
