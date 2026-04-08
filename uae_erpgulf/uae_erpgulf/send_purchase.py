
import frappe
import json
import requests
from frappe import _
from uae_erpgulf.uae_erpgulf.purchase_json  import send_invoice_json
from uae_erpgulf.uae_erpgulf.verify_token import get_flick_access_token
def send_invoice_to_flick(doc, method=None):
    """
    On Purchase Invoice Submit and after JSON generation then submission to Flick API
    """

    try:
        files = frappe.get_all(
            "File",
            filters={
                "attached_to_doctype": "Purchase Invoice",
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

        with open(file_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)
        company_doc = frappe.get_doc("Company", doc.company)
        participant_id = company_doc.custom_participant_id
       
        if not participant_id:
            frappe.throw(_("Participant ID is missing in Company"))
       
        payload = {
            "document": json_data
        }
        base_url = company_doc.custom_base_url
        url =  f"{base_url}/v1/{participant_id}/documents"
        # frappe.throw(_(url))
        auth_key = company_doc.custom_xflickauthkey
        from frappe.utils import get_datetime, now_datetime
        from datetime import timedelta

        current_time = now_datetime()
        created_time = get_datetime(company_doc.custom_token_expiry_time)

        if not created_time or current_time >= created_time + timedelta(hours=1):
            get_flick_access_token(company_doc.name)
            company_doc.reload()
        access_token = company_doc.custom_access_token

        if not participant_id:
            frappe.throw(_("Participant ID is missing in Company"))

        # Case 1: Use X-Flick Auth Key
        if auth_key:
            headers = {
                "Content-Type": "application/json",
                "X-Flick-Auth-Key": auth_key
            }

        # Case 2: Fallback to Access Token
        elif access_token:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            }

        # Case 3: Neither available
        else:
            frappe.throw(_("Both X-Flick Auth Key and Access Token are missing in Company"))
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=120
        )

        try:
            response_data = response.json()
        except Exception:
            response_data = response.text

        frappe.msgprint(
            f"<b>Status:</b> {response.status_code}<br><br>"
            f"<b>Response:</b><br>{response_data}"
        )
        return response.status_code, response_data
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Flick API Error")
        frappe.throw(_("Error while sending invoice to Flick API."))


@frappe.whitelist(allow_guest=False)
def generate_and_send_einvoice(doc, method=None):
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
        json_response = send_invoice_json(doc.name)

        if not json_response:
            frappe.throw(_("Failed to generate eInvoice JSON"))
        status_code, response_data = send_invoice_to_flick(doc)
        if isinstance(response_data, dict):
            response_text = json.dumps(response_data, indent=4)
        else:
            response_text = str(response_data)
    
        invoice_status = "Not Submitted"
        eporting_status = None  # NEW

        # ✅ Extract reporting_status safely
        if isinstance(response_data, dict):
            data = response_data.get("data", {})
            reporting_status = data.get("reporting_status")
            document_id = data.get("id")
        if status_code == 200:
            if isinstance(response_data, dict):
                if response_data.get("status") in ["success", "processed", "accepted"]:
                    invoice_status = "Success"
            else:
                invoice_status = "Success"
        # Save status
        doc.db_set("custom_submit_response", response_text)
        doc.db_set("custom_uae_einvoice_status", invoice_status)
        if reporting_status:
            doc.db_set("custom_reporting_status", reporting_status)
        if document_id:
            doc.db_set("custom_document_id", document_id)
        frappe.db.commit()

        frappe.msgprint(
            _("Flick Response Stored. Status: {0}").format(invoice_status)
        )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "UAE eInvoice Submit Error")

        frappe.msgprint(
            _("E-Invoice processing failed. Check Submit Response field.")
        )


@frappe.whitelist()
def bulk_send_invoices(invoices):
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
def get_document_status(invoice_name):
    """Fetch document status from Flick API and save response in Sales Invoice DocType"""
    try:
        sales_invoice_doc = frappe.get_doc("Purchase Invoice", invoice_name)
        company_doc = frappe.get_doc("Company", sales_invoice_doc.company)

        participant_id = company_doc.custom_participant_id
        auth_key = company_doc.custom_xflickauthkey

        if not participant_id:
            frappe.throw(_("Participant ID is missing in Company"))


        if not sales_invoice_doc.custom_submit_response:
            frappe.throw(_("Submit response not found in Sales Invoice"))

        # Extract document ID
        response_data = json.loads(sales_invoice_doc.custom_submit_response)
        document_id = response_data.get("data", {}).get("id")

        if not document_id:
            frappe.throw(_("Document ID not found in submit response"))
        base_url = company_doc.custom_base_url
        if not base_url:
            frappe.throw(_("Base URL is missing in Company"))
        url = f"{base_url}/v1/{participant_id}/documents/{document_id}"

        from frappe.utils import get_datetime, now_datetime
        from datetime import timedelta

        current_time = now_datetime()
        created_time = get_datetime(company_doc.custom_token_expiry_time)

        if not created_time or current_time >= created_time + timedelta(hours=1):
            get_flick_access_token(company_doc.name)
            company_doc.reload()
        access_token = company_doc.custom_access_token
        if auth_key:
            headers = {
                "X-Flick-Auth-Key": auth_key
            }

        # Case 2: Fallback to Access Token
        elif access_token:
            headers = {
                "Authorization": f"Bearer {access_token}"
            }

        # Case 3: Neither available
        else:
            frappe.throw(_("Both X-Flick Auth Key and Access Token are missing in Company"))
        response = requests.get(url, headers=headers)

      
        if response.status_code == 200:
            response_json = response.json()
            data = response_json.get("data", {})
            reporting_status = data.get("reporting_status")
            sales_invoice_doc.db_set(
                "custom_submit_response",
                json.dumps(response_json, indent=2)
            )
            if reporting_status:
                sales_invoice_doc.db_set(
                    "custom_reporting_status",
                    reporting_status)
                # get_document_xml(invoice_name)
            return response_json

        else:
            return {
                "status": "error",
                "message": response.text
    }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Flick Document Status Error")
        frappe.throw(_("Failed to fetch document status"))

