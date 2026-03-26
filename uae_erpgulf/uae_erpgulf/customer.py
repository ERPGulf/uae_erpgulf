import frappe
import http.client
import json
import requests
from frappe import _

@frappe.whitelist()
def custom_lookup_peppol_id_of_participant(peppol_id):
    try:
        url = f"https://sb-ae-api.flick.network/v1/peppol/lookup/{peppol_id}"
        company_doc = frappe.get_doc("Company", company)

        auth_key = company_doc.custom_xflickauthkey
        headers = {
            "X-Flick-Auth-Key": "YOUR_SECRET_TOKEN"
        }

        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            return response.json()
        else:
            frappe.throw(f"API Error: {response.text}")

    except Exception as e:
        frappe.log_error(str(e), "PEPPOL Lookup Error")
        frappe.throw(str(e))
