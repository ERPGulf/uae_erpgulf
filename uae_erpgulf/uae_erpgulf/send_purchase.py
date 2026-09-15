
# # import frappe
# # import json
# # import requests
# # from frappe import _
# # from uae_erpgulf.uae_erpgulf.purchase_json  import send_invoice_json
# # from uae_erpgulf.uae_erpgulf.provider_settings import get_active_provider_settings
# # from uae_erpgulf.uae_erpgulf.providers import get_adapter
# # from uae_erpgulf.uae_erpgulf.attach import get_document_xml
# # from uae_erpgulf.uae_erpgulf.attach import get_document_pdf
# # from uae_erpgulf.uae_erpgulf.validation import success_log
# # def send_invoice_to_provider(doc, method=None):
# #     """
# #     On Purchase Invoice Submit and after JSON generation, send it to
# #     whichever ASP this company's active E-Invoice Provider Settings row
# #     points at. Never checks a provider name directly - that's the adapter's job.
# #     """

# #     try:
# #         files = frappe.get_all(
# #             "File",
# #             filters={
# #                 "attached_to_doctype": "Purchase Invoice",
# #                 "attached_to_name": doc.name
# #             },
# #             fields=["file_url", "file_name"]
# #         )
# #         json_file = None
# #         for f in files:
# #             if f.file_name.lower().endswith(".json"):
# #                 json_file = f
# #                 break

# #         if not json_file:
# #             frappe.throw(_("No JSON attachment found."))
# #         file_doc = frappe.get_doc("File", {"file_url": json_file.file_url})
# #         file_path = file_doc.get_full_path()

# #         with open(file_path, "r", encoding="utf-8") as f: # nosemgrep: frappe-security-file-traversal
# #             json_data = json.load(f)

# #         settings = get_active_provider_settings(doc.company)
# #         adapter = get_adapter(settings)

# #         status_code, response_data = adapter.submit_invoice("Purchase Invoice", doc, json_data)

# #         data = response_data.get("data", {}) if isinstance(response_data, dict) else {}
# #         parsed = data.get("parsed", {}) if isinstance(data, dict) else {}
# #         api_status = response_data.get("status", "-") if isinstance(response_data, dict) else "-"
# #         message = response_data.get("message", "-") if isinstance(response_data, dict) else "-"

# #         html = """
# #         <style>
# #             .flick-table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
# #             .flick-table th, .flick-table td {{ border: 1px solid #d1d8dd !important; padding: 8px 12px; text-align: left; }}
# #             .flick-table thead tr {{ background-color: #f0f4f7; }}
# #             .flick-table tbody tr:nth-child(even) {{ background-color: #f9f9f9; }}
# #         </style>
# #         <table class="flick-table">
# #             <thead>
# #                 <tr><th>Field</th><th>Value</th></tr>
# #             </thead>
# #             <tbody>
# #                 <tr><td><b>API Status</b></td><td>{api_status}</td></tr>
# #                 <tr><td><b>Message</b></td><td>{message}</td></tr>
# #                 <tr><td><b>Document ID</b></td><td>{doc_id}</td></tr>
# #                 <tr><td><b>Direction</b></td><td>{direction}</td></tr>
# #                 <tr><td><b>Document Identifier</b></td><td>{doc_identifier}</td></tr>
# #                 <tr><td><b>Exchange Status</b></td><td>{exchange_status}</td></tr>
# #                 <tr><td><b>Reporting Status</b></td><td>{reporting_status}</td></tr>
# #                 <tr><td><b>Reporting Reference</b></td><td>{reporting_reference}</td></tr>
# #                 <tr><td><b>Seller Name</b></td><td>{seller_name}</td></tr>
# #                 <tr><td><b>Buyer Name</b></td><td>{buyer_name}</td></tr>
# #                 <tr><td><b>Payable Amount</b></td><td>{payable_amount}</td></tr>
# #                 <tr><td><b>Issue Date</b></td><td>{issue_date}</td></tr>
# #             </tbody>
# #         </table>
# #         """.format(
# #             api_status=api_status,
# #             message=message,
# #             doc_id=data.get("id", "-"),
# #             direction=data.get("direction", "-"),
# #             doc_identifier=data.get("document_identifier", "-"),
# #             exchange_status=data.get("exchange_status", "-"),
# #             reporting_status=data.get("reporting_status", "-"),
# #             reporting_reference=data.get("reporting_reference", "-"),
# #             seller_name=parsed.get("seller_name", "-"),
# #             buyer_name=parsed.get("buyer_name", "-"),
# #             payable_amount=parsed.get("payable_amount", "-"),
# #             issue_date=parsed.get("issue_date", "-")
# #         )
# #         if isinstance(response_data, (dict, list)):
# #             pretty_response = json.dumps(response_data, indent=2)
# #         else:
# #             pretty_response = str(response_data)

# #         html = """
# #             <p><b>HTTP Status:</b> {status_code}</p>
# #             <pre style="white-space:pre-wrap;background:#f6f8fa;padding:12px;
# #                 border-radius:6px;max-height:400px;overflow:auto;font-size:12px;">{response}</pre>
# #             """.format(
# #                 status_code=status_code,
# #                 response=frappe.utils.escape_html(pretty_response),
# #             )
# #         frappe.msgprint(html, title="Simulated Incoming Invoice", wide=True)
# #         return status_code, response_data

# #     except Exception:
# #         frappe.log_error(frappe.get_traceback(), "E-Invoice Submit Error")
# #         frappe.throw(_("Error while sending invoice to the e-invoicing provider."))


# # from typing import Optional, Union
# # from frappe.model.document import Document
# # @frappe.whitelist(allow_guest=False)
# # def generate_and_send_einvoice(doc: Union[Document, str], method: Optional[str] = None):
# #     """
# #     Store Success/Failed in custom_uae_einvoice_status
# #     """

# #     if isinstance(doc, str):
# #         doc = frappe.parse_json(doc)

# #     if isinstance(doc, dict):
# #         doc = frappe.get_doc(doc)
# #     if doc.doctype != "Purchase Invoice":
# #         return

# #     try:
# #         json_response = send_invoice_json(doc.name)

# #         if not json_response:
# #             frappe.throw(_("Failed to generate eInvoice JSON"))
# #         status_code, response_data = send_invoice_to_provider(doc)
# #         if isinstance(response_data, dict):
# #             response_text = json.dumps(response_data, indent=4)
# #         else:
# #             response_text = str(response_data)

# #         invoice_status = "Not Submitted"
# #         reporting_status = None
# #         document_id = None

# #         # Extract reporting_status safely
# #         if isinstance(response_data, dict):
# #             data = response_data.get("data", {})
# #             reporting_status = data.get("reporting_status")
# #             document_id = data.get("id")

# #         if status_code in (200, 201):
# #             if isinstance(response_data, dict):
# #                 if response_data.get("status") in ["success", "processed", "accepted"] or document_id:
# #                     invoice_status = "Success"
# #             else:
# #                 invoice_status = "Success"
# #         # Save status

# #         doc.db_set("custom_submit_response", response_text)
# #         if status_code in (200, 201):
# #             try:
# #                 get_document_xml("Purchase Invoice", doc.name)
# #                 get_document_pdf("Purchase Invoice", doc.name)
# #             except Exception:
# #                 frappe.log_error(frappe.get_traceback(), "E-Invoice XML/PDF Fetch Error")
# #         doc.db_set("custom_uae_einvoice_status", invoice_status)
# #         if reporting_status:
# #             doc.db_set("custom_reporting_status", reporting_status)
# #         if document_id:
# #             doc.db_set("custom_document_id", document_id)
# #         frappe.db.commit()

# #         exchange_status = None

# #         if isinstance(response_data, dict):
# #             data = response_data.get("data", {})
# #             exchange_status = data.get("exchange_status")
# #         if status_code in (200, 201):
# #             settings = get_active_provider_settings(doc.company)

# #             success_log(
# #                 title="UAE E-Invoice Submitted Successfully",
# #                 document_id=document_id,
# #                 participant_id=settings.participant_id,
# #                 invoice_number=doc.name,
# #                 reporting_status=reporting_status,
# #                 exchange_status=exchange_status,
# #                 status=invoice_status,
# #                 submit_response=response_text,
# #             )
# #         # frappe.msgprint(
# #         #     _("Flick Response Stored. Status: {0}").format(invoice_status)
# #         # )

# #     except Exception:
# #         frappe.log_error(frappe.get_traceback(), "UAE eInvoice Submit Error")

# #         frappe.msgprint(
# #             _("E-Invoice processing failed. Check Submit Response field.")
# #         )


# # @frappe.whitelist()
# # def bulk_send_invoices(invoices: list | str):
# #     """Bulk send multiple invoices to FTA, with error handling and status tracking."""
# #     if isinstance(invoices, str):
# #         invoices = frappe.parse_json(invoices)

# #     success = []
# #     skipped = []
# #     failed = []

# #     for invoice in invoices:
# #         try:
# #             # Load documents
# #             doc = frappe.get_doc("Purchase Invoice", invoice)
# #             company_doc = frappe.get_doc("Company", doc.company)

# #             status = doc.custom_uae_einvoice_status

# #             # Skip already submitted invoices
# #             if status == "Success":
# #                 skipped.append(invoice)
# #                 continue

# #             # If invoice is Draft → Submit first
# #             if doc.docstatus == 0 and company_doc.custom_uae_einvoice_enabled == 1:
# #                 doc.submit()

# #             # If invoice is Submitted → Send to FTA
# #             if doc.docstatus == 1 and company_doc.custom_uae_einvoice_enabled == 1:
# #                 generate_and_send_einvoice(doc)
# #                 success.append(invoice)

# #         except Exception as e:
# #             frappe.log_error(frappe.get_traceback(), f"FTA Bulk Submission Error: {invoice}")
# #             failed.append(f"{invoice} : {str(e)}")

# #     return {
# #         "success": success,
# #         "skipped": skipped,
# #         "failed": failed
# #     }




# # @frappe.whitelist()
# # def get_document_status(invoice_name: str):
# #     """Fetch document status from this company's active provider and save
# #     the response in the Purchase Invoice."""
# #     try:
# #         purchase_invoice_doc = frappe.get_doc("Purchase Invoice", invoice_name)
# #         settings = get_active_provider_settings(purchase_invoice_doc.company)
# #         adapter = get_adapter(settings)

# #         response_json = adapter.get_document_status("Purchase Invoice", purchase_invoice_doc)

# #         if isinstance(response_json, dict) and response_json.get("data"):
# #             data = response_json.get("data", {})
# #             reporting_status = data.get("reporting_status")
# #             purchase_invoice_doc.db_set(
# #                 "custom_document_status_response",
# #                 json.dumps(response_json)
# #             )
# #             if reporting_status:
# #                 purchase_invoice_doc.db_set("custom_reporting_status", reporting_status)

# #         return response_json
# #     except Exception:
# #         frappe.log_error(frappe.get_traceback(), "E-Invoice Document Status Error")
# #         frappe.throw(_("Failed to fetch document status"))
# import frappe
# import json
# import requests
# from frappe import _
# from uae_erpgulf.uae_erpgulf.purchase_json  import send_invoice_json
# from uae_erpgulf.uae_erpgulf.provider_settings import get_active_provider_settings
# from uae_erpgulf.uae_erpgulf.providers import get_adapter
# from uae_erpgulf.uae_erpgulf.attach import get_document_xml
# from uae_erpgulf.uae_erpgulf.attach import get_document_pdf
# from uae_erpgulf.uae_erpgulf.validation import success_log
# def send_invoice_to_provider(doc, method=None):
#     """
#     On Purchase Invoice Submit and after JSON generation, send it to
#     whichever ASP this company's active E-Invoice Provider Settings row
#     points at. Never checks a provider name directly - that's the adapter's job.
#     """

#     try:
#         files = frappe.get_all(
#             "File",
#             filters={
#                 "attached_to_doctype": "Purchase Invoice",
#                 "attached_to_name": doc.name
#             },
#             fields=["file_url", "file_name"]
#         )
#         json_file = None
#         for f in files:
#             if f.file_name.lower().endswith(".json"):
#                 json_file = f
#                 break

#         if not json_file:
#             frappe.throw(_("No JSON attachment found."))
#         file_doc = frappe.get_doc("File", {"file_url": json_file.file_url})
#         file_path = file_doc.get_full_path()

#         with open(file_path, "r", encoding="utf-8") as f: # nosemgrep: frappe-security-file-traversal
#             json_data = json.load(f)

#         settings = get_active_provider_settings(doc.company)
#         adapter = get_adapter(settings)

#         status_code, response_data = adapter.submit_invoice("Purchase Invoice", doc, json_data)

#         # Different ASPs shape their response completely differently - show
#         # the raw response rather than guessing at one provider's field
#         # names in this shared file.
#         if isinstance(response_data, (dict, list)):
#             pretty_response = json.dumps(response_data, indent=2)
#         else:
#             pretty_response = str(response_data)

#         html = """
#             <p><b>HTTP Status:</b> {status_code}</p>
#             <pre style="white-space:pre-wrap;background:#f6f8fa;padding:12px;
#                 border-radius:6px;max-height:400px;overflow:auto;font-size:12px;">{response}</pre>
#             """.format(
#                 status_code=status_code,
#                 response=frappe.utils.escape_html(pretty_response),
#             )

#         frappe.msgprint(html, title="Simulated Incoming Invoice", wide=True)
#         return status_code, response_data

#     except Exception:
#         frappe.log_error(frappe.get_traceback(), "E-Invoice Submit Error")
#         frappe.throw(_("Error while sending invoice to the e-invoicing provider."))


# from typing import Optional, Union
# from frappe.model.document import Document
# @frappe.whitelist(allow_guest=False)
# def generate_and_send_einvoice(doc: Union[Document, str], method: Optional[str] = None):
#     """
#     Store Success/Failed in custom_uae_einvoice_status
#     """

#     if isinstance(doc, str):
#         doc = frappe.parse_json(doc)

#     if isinstance(doc, dict):
#         doc = frappe.get_doc(doc)
#     if doc.doctype != "Purchase Invoice":
#         return

#     try:
#         json_response = send_invoice_json(doc.name)

#         if not json_response:
#             frappe.throw(_("Failed to generate eInvoice JSON"))
#         status_code, response_data = send_invoice_to_provider(doc)
#         if isinstance(response_data, dict):
#             response_text = json.dumps(response_data, indent=4)
#         else:
#             response_text = str(response_data)

#         invoice_status = "Not Submitted"
#         reporting_status = None
#         document_id = None

#         # Extract reporting_status safely
#         if isinstance(response_data, dict):
#             data = response_data.get("data", {})
#             reporting_status = data.get("reporting_status")
#             document_id = data.get("id")

#         if status_code in (200, 201):
#             if isinstance(response_data, dict):
#                 if response_data.get("status") in ["success", "processed", "accepted"] or document_id:
#                     invoice_status = "Success"
#             else:
#                 invoice_status = "Success"
#         # Save status

#         doc.db_set("custom_submit_response", response_text)
#         if status_code in (200, 201):
#             try:
#                 get_document_xml("Purchase Invoice", doc.name)
#                 get_document_pdf("Purchase Invoice", doc.name)
#             except Exception:
#                 frappe.log_error(frappe.get_traceback(), "E-Invoice XML/PDF Fetch Error")
#         doc.db_set("custom_uae_einvoice_status", invoice_status)
#         if reporting_status:
#             doc.db_set("custom_reporting_status", reporting_status)
#         if document_id:
#             doc.db_set("custom_document_id", document_id)
#         frappe.db.commit()

#         exchange_status = None

#         if isinstance(response_data, dict):
#             data = response_data.get("data", {})
#             exchange_status = data.get("exchange_status")
#         if status_code in (200, 201):
#             settings = get_active_provider_settings(doc.company)

#             success_log(
#                 title="UAE E-Invoice Submitted Successfully",
#                 document_id=document_id,
#                 participant_id=settings.participant_id,
#                 invoice_number=doc.name,
#                 reporting_status=reporting_status,
#                 exchange_status=exchange_status,
#                 status=invoice_status,
#                 submit_response=response_text,
#             )
#         # frappe.msgprint(
#         #     _("Flick Response Stored. Status: {0}").format(invoice_status)
#         # )

#     except Exception:
#         frappe.log_error(frappe.get_traceback(), "UAE eInvoice Submit Error")

#         frappe.msgprint(
#             _("E-Invoice processing failed. Check Submit Response field.")
#         )


# @frappe.whitelist()
# def bulk_send_invoices(invoices: list | str):
#     """Bulk send multiple invoices to FTA, with error handling and status tracking."""
#     if isinstance(invoices, str):
#         invoices = frappe.parse_json(invoices)

#     success = []
#     skipped = []
#     failed = []

#     for invoice in invoices:
#         try:
#             # Load documents
#             doc = frappe.get_doc("Purchase Invoice", invoice)
#             company_doc = frappe.get_doc("Company", doc.company)

#             status = doc.custom_uae_einvoice_status

#             # Skip already submitted invoices
#             if status == "Success":
#                 skipped.append(invoice)
#                 continue

#             # If invoice is Draft → Submit first
#             if doc.docstatus == 0 and company_doc.custom_uae_einvoice_enabled == 1:
#                 doc.submit()

#             # If invoice is Submitted → Send to FTA
#             if doc.docstatus == 1 and company_doc.custom_uae_einvoice_enabled == 1:
#                 generate_and_send_einvoice(doc)
#                 success.append(invoice)

#         except Exception as e:
#             frappe.log_error(frappe.get_traceback(), f"FTA Bulk Submission Error: {invoice}")
#             failed.append(f"{invoice} : {str(e)}")

#     return {
#         "success": success,
#         "skipped": skipped,
#         "failed": failed
#     }




# @frappe.whitelist()
# def get_document_status(invoice_name: str):
#     """Fetch document status from this company's active provider and save
#     the response in the Purchase Invoice."""
#     try:
#         purchase_invoice_doc = frappe.get_doc("Purchase Invoice", invoice_name)
#         settings = get_active_provider_settings(purchase_invoice_doc.company)
#         adapter = get_adapter(settings)

#         result = adapter.get_document_status("Purchase Invoice", purchase_invoice_doc)

#         # Same envelope both adapters now always return from
#         # get_document_status - see verify_token.py's get_document_status
#         # (the Sales Invoice equivalent of this function) for the full
#         # reasoning. This also fixes the same latent bug that one had: the
#         # old `if response_json.get("data")` check meant a response with no
#         # "data" key (Marmin's shape, or Flick's own error shape) silently
#         # saved nothing at all instead of saving the raw body.
#         if isinstance(result, dict) and "http_status" in result:
#             http_status = result.get("http_status")
#             body = result.get("response")
#         else:
#             http_status = None
#             body = result

#         purchase_invoice_doc.db_set(
#             "custom_document_status_response",
#             json.dumps(body)
#         )

#         # Prefer an adapter-supplied reporting_status (Marmin derives one
#         # from its event-log body - see MarminAdapter._reporting_status_
#         # from_status_logs and verify_token.py's get_document_status,
#         # the Sales Invoice equivalent of this function, for the full
#         # reasoning) before falling back to sniffing Flick's own
#         # {"data": {"reporting_status": ...}} shape.
#         reporting_status = result.get("reporting_status") if isinstance(result, dict) else None
#         if not reporting_status and isinstance(body, dict):
#             data = body.get("data", {})
#             reporting_status = data.get("reporting_status") or body.get("reporting_status")
#         if reporting_status:
#             purchase_invoice_doc.db_set("custom_reporting_status", reporting_status)

#         return {"http_status": http_status, "response": body}
#     except Exception as e:
#         frappe.log_error(frappe.get_traceback(), "E-Invoice Document Status Error")
#         frappe.throw(_("Failed to fetch document status: {0}").format(str(e)))

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
    """
    On Purchase Invoice Submit and after JSON generation, send it to
    whichever ASP this company's active E-Invoice Provider Settings row
    points at. Never checks a provider name directly - that's the adapter's job.
    """

    try:
        settings = get_active_provider_settings(doc.company)
        adapter = get_adapter(settings)

        json_data = None
        if getattr(adapter, "USES_SHARED_INVOICE_JSON", True):
            # Same fix as Sales Invoice's send_invoice_to_provider
            # (test.py): match ONLY the shared "<invoice>_uae_invoice.json"
            # file by name, not just "the first attachment ending in
            # .json" - an ASP that also attaches its own request-payload
            # file via save_outgoing_payload() (Marmin does; see
            # providers/base.py) means a Purchase Invoice can carry more
            # than one ".json" attachment, so picking "any .json file"
            # could grab the wrong one.
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

        # Different ASPs shape their response completely differently - show
        # the raw response rather than guessing at one provider's field
        # names in this shared file.
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
        # Same fix as Sales Invoice's send_invoice_to_provider (test.py):
        # show the real reason (str(e)) instead of always the same fixed
        # sentence, which used to hide a perfectly specific message (e.g.
        # an adapter's own frappe.throw("Supplier ... has no PEPPOL ID
        # set...")) behind a generic one.
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

        # Same fix as Sales Invoice's generate_and_send_einvoice (test.py):
        # only build/attach the shared "<invoice>_uae_invoice.json" file
        # for a provider whose adapter actually uses it (Flick does, via
        # USES_SHARED_INVOICE_JSON on BaseAdapter/its subclasses) - Marmin
        # builds its own payload straight from doc and never reads this
        # file, so generating it here was just noise on every purchase
        # invoice, and it's exactly why Marmin invoices ended up with two
        # JSON attachments (this shared one, plus Marmin's own outgoing
        # payload file from save_outgoing_payload()).
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

        # Extract reporting_status safely. Flick nests everything under
        # "data" ({"data": {"id": ..., "reporting_status": ...}}); Marmin's
        # response is flat (id/reporting_status straight at the top level) -
        # try the nested shape first, then fall back to the flat one, same
        # as Sales Invoice's generate_and_send_einvoice (test.py).
        if isinstance(response_data, dict):
            data = response_data.get("data", {})
            reporting_status = data.get("reporting_status") or response_data.get("reporting_status")
            document_id = data.get("id") or response_data.get("id")

        # 200 = Flick's success code, 201 Created = Marmin's - both mean
        # "accepted", so both count here.
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
            # Same retry loop as Sales Invoice's generate_and_send_einvoice
            # (test.py): give an ASP whose XML/PDF are generated
            # asynchronously (Marmin - see DOCUMENT_FETCH_RETRY_ATTEMPTS/
            # DELAY_SECONDS on its adapter) a few short-spaced tries before
            # giving up quietly, instead of one flat attempt that logs an
            # error on every Marmin purchase invoice submit just because
            # the document wasn't ready yet.
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
                    # Same message-log snapshot/truncate trick as test.py -
                    # frappe.throw() queues its message via msgprint() the
                    # moment it's called, before raising, so a swallowed/
                    # retried fetch failure would otherwise still surface
                    # in this submit's own response.
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
        # Same "pending" default as Sales Invoice's generate_and_send_
        # einvoice (test.py): Marmin's submit response carries no
        # reporting_status field at all, so a genuinely successful submit
        # would otherwise leave this blank until someone clicks "Get
        # Document Status" later - default to "pending" instead, without
        # overriding a real value Flick's own response already gave.
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
        # Same fix as Sales Invoice's generate_and_send_einvoice (test.py):
        # show the real reason instead of always "Check Submit Response
        # field" even when Submit Response was never written yet (the
        # failure happened before that db_set ever ran).
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

        # Same envelope both adapters now always return from
        # get_document_status - see verify_token.py's get_document_status
        # (the Sales Invoice equivalent of this function) for the full
        # reasoning. This also fixes the same latent bug that one had: the
        # old `if response_json.get("data")` check meant a response with no
        # "data" key (Marmin's shape, or Flick's own error shape) silently
        # saved nothing at all instead of saving the raw body.
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

        # Prefer an adapter-supplied reporting_status (Marmin derives one
        # from its event-log body - see MarminAdapter._reporting_status_
        # from_status_logs and verify_token.py's get_document_status,
        # the Sales Invoice equivalent of this function, for the full
        # reasoning) before falling back to sniffing Flick's own
        # {"data": {"reporting_status": ...}} shape.
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