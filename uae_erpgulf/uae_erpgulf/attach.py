import frappe
import requests
import json
from frappe import _

@frappe.whitelist()
def get_document_xml(invoice_name):
    try:
        sales_invoice_doc = frappe.get_doc("Sales Invoice", invoice_name)
        company_doc = frappe.get_doc("Company", sales_invoice_doc.company)

        participant_id = company_doc.custom_participant_id
        auth_key = company_doc.custom_xflickauthkey

        if not participant_id:
            frappe.throw(_("Participant ID is missing in Company"))

        if not auth_key:
            frappe.throw(_("X-Flick Auth Key is missing in Company"))

        if not sales_invoice_doc.custom_submit_response:
            frappe.throw(_("Submit response not found in Sales Invoice"))

        # Extract document_id from submit response
        response_data = json.loads(sales_invoice_doc.custom_submit_response)
        document_id = response_data.get("data", {}).get("id")
        base_url = company_doc.custom_base_url
        if not document_id:
            frappe.throw(_("Document ID not found in submit response"))

        url = f"{base_url}/v1/{participant_id}/documents/{document_id}/xml"

        headers = {
            "X-Flick-Auth-Key": auth_key
        }

        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            xml_data = response.text

            # Save XML response in Sales Invoice
            sales_invoice_doc.db_set(
                "custom_document_xml",
                xml_data
            )

            return {
                "status": "success",
                "message": "XML fetched successfully"
            }

        else:
            frappe.throw(_("API Error: {0}").format(response.text))

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Flick XML Fetch Error")
        frappe.throw(_("Failed to fetch document XML"))



@frappe.whitelist()
def get_document_pdf(invoice_name):
    try:
        sales_invoice_doc = frappe.get_doc("Sales Invoice", invoice_name)
        company_doc = frappe.get_doc("Company", sales_invoice_doc.company)

        participant_id = company_doc.custom_participant_id
        auth_key = company_doc.custom_xflickauthkey

        if not participant_id:
            frappe.throw(_("Participant ID is missing in Company"))

        if not auth_key:
            frappe.throw(_("X-Flick Auth Key is missing in Company"))

        if not sales_invoice_doc.custom_submit_response:
            frappe.throw(_("Submit response not found in Sales Invoice"))
        
        # Extract document_id
        response_data = json.loads(sales_invoice_doc.custom_submit_response)
        document_id = response_data.get("data", {}).get("id")

        if not document_id:
            frappe.throw(_("Document ID not found in submit response"))
        base_url = company_doc.custom_base_url
        url = f"{base_url}/v1/{participant_id}/documents/{document_id}/pdf"

        headers = {
            "X-Flick-Auth-Key": auth_key
        }

        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            pdf_data = response.content

            # Save PDF (base64) in field
            sales_invoice_doc.db_set(
                "custom_document_pdf",
                pdf_data
            )

            return {"status": "success", "message": "PDF fetched successfully"}

        else:
            frappe.throw(_("API Error: {0}").format(response.text))

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Flick PDF Fetch Error")
        frappe.throw(_("Failed to fetch document PDF"))