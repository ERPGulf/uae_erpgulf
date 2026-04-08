import frappe
import http.client
import json
import requests
from frappe import _
from datetime import now_datetime
import pytz

from uae_erpgulf.uae_erpgulf.attach import get_document_xml


@frappe.whitelist(allow_guest=False)
def verify_flick_token(company):
    """Verify Flick token using fields inside Company DocType"""

    doc = frappe.get_doc("Company", company)

    base_url = doc.custom_base_url
    auth_key = doc.custom_xflickauthkey

    if not base_url or not auth_key:
        frappe.throw(_("Please enter Base URL and X-Flick-Auth-Key in Company."))

    try:
        url = f"{base_url}/v1/auth/verify"
        headers = {
            "X-Flick-Auth-Key": auth_key
        }
        response = requests.get(url, headers=headers)
        response_text = response.text
        doc.custom_token_response = response_text
        doc.save(ignore_permissions=True)
        return {
            "status": "success",
            "response": response_text
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Flick Verify Error")
        return {
            "status": "error",
            "message": str(e)
        }

@frappe.whitelist(allow_guest=False)
def get_participant_details(company):
    """Fetch participant details from Flick API and save response in Company DocType"""
    company_doc = frappe.get_doc("Company", company)
    base_url = company_doc.custom_base_url
    if not base_url:
        frappe.throw(_("Please enter Base URL and X-Flick-Auth-Key in Company."))
    participant_id = company_doc.custom_participant_id
    auth_key = company_doc.custom_xflickauthkey
    if not participant_id:
        frappe.throw(_("Participant ID is missing in Company"))
    if not auth_key:
        frappe.throw(_("X-Flick Auth Key is missing in Company"))

    url = f"{base_url}/v1/participants/{participant_id}"

    headers = {
        "X-Flick-Auth-Key": auth_key
    }
    response = requests.get(url, headers=headers)
    data = response.json()
    company_doc.custom_participant_details_response = json.dumps(data, indent=4)
    company_doc.save(ignore_permissions=True)
    return {
        "status": "success",
        "response": data
    }



@frappe.whitelist()
def get_document_status(invoice_name):
    """Fetch document status from Flick API and save response in Sales Invoice DocType"""
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

        # Extract document ID
        response_data = json.loads(sales_invoice_doc.custom_submit_response)
        document_id = response_data.get("data", {}).get("id")

        if not document_id:
            frappe.throw(_("Document ID not found in submit response"))
        base_url = company_doc.custom_base_url
        if not base_url:
            frappe.throw(_("Base URL is missing in Company"))
        url = f"{base_url}/v1/{participant_id}/documents/{document_id}"

        headers = {
            "X-Flick-Auth-Key": auth_key
        }

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
            #   get_document_xml(invoice_name)
            return response_json

        else:
            return {
                "status": "error",
                "message": response.text
    }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Flick Document Status Error")
        frappe.throw(_("Failed to fetch document status"))




@frappe.whitelist(allow_guest=False)
def get_flick_access_token(company:str):
    """Fetch access token from Flick API using Client ID and Client Secret stored in Company DocType"""
    doc = frappe.get_doc("Company", company)
    base_url = doc.custom_base_url
    client_id = doc.custom_client_id
    if not base_url or not client_id or not doc.custom_client_secret:
        frappe.throw(_("Please enter Base URL, Client ID and Client Secret in Company."))
    client_secret = doc.custom_client_secret
    url = f"{base_url}/v1/oauth/token"
    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()  # raises error for bad responses
        response_json = response.json()
        frappe.msgprint(f"Token Response: {response_json}")
        access_token = response_json.get("access_token")

        if not access_token:
            frappe.throw(_("Access token not found in response"))
          # default 1 hour
        dubai_tz = pytz.timezone("Asia/Dubai")

        # Convert current time to Dubai
        current_time = now_datetime().astimezone(dubai_tz)
        doc.db_set("custom_token_expiry_time",current_time)
        doc.db_set("custom_access_token", access_token)

        frappe.db.commit()
        return response.json()

    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "message": str(e)
        }
