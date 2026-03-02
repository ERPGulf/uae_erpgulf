import frappe
import json
import requests
from frappe import _
from uae_erpgulf.uae_erpgulf.your_json_file import build_uae_invoice_json


def send_invoice_to_flick(doc, method=None):
    """
    Automatically called on Sales Invoice Submit
    """

    # 1️⃣ Check UAE e-invoice enabled
    company = frappe.get_doc("Company", doc.company)
    if not company.custom_uae_einvoice_enabled:
        return

    try:
        # 2️⃣ Build JSON from your existing generator
        invoice_json = build_uae_invoice_json(doc.name)

        payload = {
            "document": invoice_json
        }

        # 3️⃣ Read API settings from site_config
        flick_api_url = frappe.conf.get("flick_api_url")
        flick_company_uuid = frappe.conf.get("flick_company_uuid")
        flick_auth_key = frappe.conf.get("flick_auth_key")

        if not flick_api_url or not flick_company_uuid or not flick_auth_key:
            frappe.throw(_("Flick API credentials not configured in site_config.json"))

        # 4️⃣ Build Final URL
        final_url = f"{flick_api_url}/{flick_company_uuid}/documents/process"

        headers = {
            "Content-Type": "application/json",
            "X-Flick-Auth-Key": flick_auth_key
        }

        # 5️⃣ Call API
        response = requests.post(
            final_url,
            headers=headers,
            json=payload,
            timeout=60
        )

        # 6️⃣ Parse Response
        try:
            response_data = response.json()
        except Exception:
            response_data = response.text

        # 7️⃣ Save response in invoice
        doc.db_set("custom_flick_status_code", response.status_code)
        # doc.db_set("custom_flick_response", json.dumps(response_data, indent=2))

        # 8️⃣ If API failed → stop submission
        if response.status_code not in (200, 201):
            frappe.throw(
                _("Flick API Error: {0}").format(response_data)
            )

        frappe.msgprint(_("UAE E-Invoice successfully submitted to Flick"))

    except Exception:
        frappe.log_error(
            title="Flick API Submission Error",
            message=frappe.get_traceback()
        )
        frappe.throw(_("Failed to send invoice to Flick. Check Error Log."))