import frappe
import json
import requests
from frappe import _
from uae_erpgulf.uae_erpgulf.verify_token import get_valid_flick_token
from frappe.utils.file_manager import save_file

    
@frappe.whitelist()
def get_document_xml(doctype,invoice_name):
    """Fetch XML from Flick API and save in Sales Invoice
    """
    try:
        doc = frappe.get_doc(doctype, invoice_name)
        company_doc = frappe.get_doc("Company", doc.company)

        participant_id = company_doc.custom_participant_id
        auth_key = company_doc.custom_xflickauthkey
        
        if not participant_id:
            frappe.throw(_("Participant ID is missing in Company"))

        if not doc.custom_submit_response:
            frappe.throw(_("Submit response not found in Invoice"))

        # Extract document_id from submit response
        response_data = json.loads(doc.custom_submit_response)
        
        document_id = response_data.get("data", {}).get("id")
        base_url = company_doc.custom_base_url
        if not document_id:
            frappe.throw(_("Document ID not found in submit response"))

        url = f"{base_url}/v1/{participant_id}/documents/{document_id}/xml"
        # headers = {
        #     "X-Flick-Auth-Key": auth_key
        # }
        access_token = get_valid_flick_token(company_doc.name)
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
        # frappe.throw(_("API Response: {0}").format(response.status_code))

        from frappe.utils.file_manager import save_file
        if response.status_code == 200:
            xml_data = response.text
 
            # Save file and get file doc
            if doc.custom_document_xml:
                old_file = frappe.get_all(
                    "File",
                    filters={"file_url": doc.custom_document_xml},
                    fields=["name"]
                )
                if old_file:
                    for f in old_file:
                        frappe.delete_doc("File", f.name, force=1)

            # ✅ SAVE NEW FILE
            file_doc = save_file(
                fname=f"Submitted-XML-file {doc.name}.xml",
                content=xml_data,
                dt=doctype,   # dynamic doctype
                dn=doc.name,
                is_private=1
            )

            # ✅ UPDATE FIELD
            doc.db_set("custom_document_xml", file_doc.file_url)

            frappe.db.commit()

            return {
                "status": "success",
                "file_url": file_doc.file_url
            }

        else:
            frappe.throw(_("API Error: {0}").format(response.text))

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Flick XML Fetch Error")
        frappe.throw(_("Failed to fetch document XML"))



@frappe.whitelist()
def get_document_pdf(doctype,invoice_name):
    """Fetch PDF from Flick API and save in Sales Invoice
    """
    try:
        # sales_invoice_doc = frappe.get_doc("Sales Invoice", invoice_name)
        doc = frappe.get_doc(doctype, invoice_name)
        company_doc = frappe.get_doc("Company", doc.company)

        participant_id = company_doc.custom_participant_id
        auth_key = company_doc.custom_xflickauthkey

        if not participant_id:
            frappe.throw(_("Participant ID is missing in Company"))


        if not doc.custom_submit_response:
            frappe.throw(_("Submit response not found in Invoice"))
        
        # Extract document_id
        response_data = json.loads(doc.custom_submit_response)
        document_id = response_data.get("data", {}).get("id")

        if not document_id:
            frappe.throw(_("Document ID not found in submit response"))
        base_url = company_doc.custom_base_url
        url = f"{base_url}/v1/{participant_id}/documents/{document_id}/pdf"

        
        access_token = get_valid_flick_token(company_doc.name)
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
            pdf_data = response.content
            if doc.custom_document_pdf:
                old_file = frappe.get_all(
                    "File",
                    filters={"file_url": doc.custom_document_pdf},
                    fields=["name"]
                )
                if old_file:
                    frappe.delete_doc("File", old_file[0].name, force=1)

            # ✅ SAVE NEW FILE
            file_doc = save_file(
                fname=f"Submitted-PDF-file {doc.name}.pdf",
                content=pdf_data,
                dt=doctype,   # ✅ use dynamic doctype
                dn=doc.name,
                is_private=1
            )

            # ✅ UPDATE FIELD
            doc.db_set("custom_document_pdf", file_doc.file_url)

            frappe.db.commit()

            return {
                "status": "success",
                "file_url": file_doc.file_url
            }

        else:
            frappe.throw(_("API Error: {0}").format(response.text))

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Flick PDF Fetch Error")
        frappe.throw(_("Failed to fetch document PDF"))