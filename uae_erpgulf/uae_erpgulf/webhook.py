import frappe
import requests
import json
from frappe import _
from frappe.utils import get_datetime, now_datetime
from datetime import timedelta
from uae_erpgulf.uae_erpgulf.verify_token import get_flick_access_token


@frappe.whitelist(allow_guest=True)
def flick_webhook_listener():
    """Listener for Flick API webhooks. Logs incoming data and updates invoice status."""
    try:
        raw_data = frappe.request.get_data(as_text=True)
        data = json.loads(raw_data)

        # 🔹 Extract top-level fields
        event_type = data.get("event")
        participant_id = data.get("participant_id")

        # 🔹 Extract nested data
        doc_data = data.get("data", {})

        document_id = doc_data.get("document_id")
        status = doc_data.get("status")
        exchange_status = doc_data.get("exchange_status")
        reporting_status = doc_data.get("reporting_status")
        invoice_number = doc_data.get("document_identifier")

        # ✅ Create Webhook Log Doc
        doc = frappe.get_doc({
            "doctype": "UAE E-Invoice Webhook Logs",
            "webhook_response": raw_data,
            "document_id": document_id,
            "participant_id": participant_id,
            "event_type": event_type,
            "reporting_status": reporting_status,
            "exchange_status": exchange_status,
            "invoice_number":invoice_number,
            "status": status
        })

        doc.insert(ignore_permissions=True)
        if document_id and reporting_status:

            # 🔹 Sales Invoice
            sales_invoice = frappe.db.get_value(
                "Sales Invoice",
                {"custom_document_id": document_id},
                "name"
            )

            if sales_invoice:
                frappe.db.set_value(
                    "Sales Invoice",
                    sales_invoice,
                    "custom_reporting_status",
                    reporting_status
                )

            # 🔹 Purchase Invoice
            purchase_invoice = frappe.db.get_value(
                "Purchase Invoice",
                {"custom_document_id": document_id},
                "name"
            )

            if purchase_invoice:
                frappe.db.set_value(
                    "Purchase Invoice",
                    purchase_invoice,
                    "custom_reporting_status",
                    reporting_status
                )

        # frappe.db.commit()
        frappe.db.commit()

        return {
            "acknowledged": True,
            "processed": True
        }

    except Exception:
        frappe.log_error(
            title="Webhook Processing Error",
            message=frappe.get_traceback()
        )
        return {
            "acknowledged": False,
            "processed": False
        }



@frappe.whitelist(allow_guest=True)
def register_flick_webhook(company):
    company_doc = frappe.get_doc("Company", company)
    base_url = company_doc.custom_base_url
    url = f"{base_url}/v1/webhooks/subscriptions"
    participant_id = company_doc.custom_participant_id
    

    current_time = now_datetime()
    created_time = get_datetime(company_doc.custom_token_expiry_time)

    if not created_time or current_time >= created_time + timedelta(hours=1):
        get_flick_access_token(company_doc.name)
        company_doc.reload()
    access_token = company_doc.custom_access_token
    if company_doc.custom_xflickauthkey :
        headers = {
            "Content-Type": "application/json",
            "X-Flick-Auth-Key": company_doc.custom_xflickauthkey 
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
        
    endpoint = frappe.utils.get_url(
    "/api/method/uae_erpgulf.uae_erpgulf.webhook.flick_webhook_listener"
        )
    payload = {
        "name": "ERPNext Webhook",
        "endpoint": endpoint,
        "event_types": [
        "document.received",
        "document.exchange.delivered",
        "document.exchange.failed",
        "document.reporting.reported",
        "document.reporting.failed",
        "document.completed",
        "document.failed"
            ],
        "participant_ids": [participant_id]
    }

    response = requests.post(url, headers=headers, json=payload)

    # Log response for debugging
    # frappe.log_error(
    #     title="Webhook Registration Response",
    #     message=response.text
    # )
    try:
        response_data = response.json()
    except Exception:
        response_data = {"raw_response": response.text}

    # ✅ Save to Company field
    company_doc.custom_webhook_subscription_response = json.dumps(response_data, indent=2)
    if response_data.get("data") and response_data["data"].get("uuid"):
        company_doc.custom_uuid_of_webhook = response_data["data"]["uuid"]
    if response_data.get("data") and response_data["data"].get("secret"):
        company_doc.custom_secret_of_webhook = response_data["data"]["secret"]
    company_doc.save(ignore_permissions=True)

    return response.json()


@frappe.whitelist()
def custom_get_subscription(company):
    company_doc = frappe.get_doc("Company", company)

    base_url = company_doc.custom_base_url
    uuid = company_doc.custom_uuid_of_webhook  # you must store this when creating webhook

    if not uuid:
        frappe.throw("Webhook UUID not found. Please create subscription first.")

    url = f"{base_url}/v1/webhooks/subscriptions/{uuid}"
    current_time = now_datetime()
    created_time = get_datetime(company_doc.custom_token_expiry_time)

    if not created_time or current_time >= created_time + timedelta(hours=1):
        get_flick_access_token(company_doc.name)
        company_doc.reload()
    access_token = company_doc.custom_access_token
    if company_doc.custom_xflickauthkey :
        headers = {
            "X-Flick-Auth-Key": company_doc.custom_xflickauthkey 
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

    try:
        response_data = response.json()
    except Exception:
        response_data = {"raw_response": response.text}

    # ✅ Save response in Company
    company_doc.custom_get_subscription_response = json.dumps(response_data, indent=2)
    company_doc.save(ignore_permissions=True)

    return response_data

@frappe.whitelist()
def get_webhook_deliveries(company):
    company_doc = frappe.get_doc("Company", company)

    base_url = company_doc.custom_base_url
    uuid = company_doc.custom_uuid_of_webhook

    url = f"{base_url}/v1/webhooks/subscriptions/{uuid}/deliveries"
    current_time = now_datetime()
    created_time = get_datetime(company_doc.custom_token_expiry_time)

    if not created_time or current_time >= created_time + timedelta(hours=1):
        get_flick_access_token(company_doc.name)
        company_doc.reload()
    access_token = company_doc.custom_access_token
    if company_doc.custom_xflickauthkey :
        headers = {
            "X-Flick-Auth-Key": company_doc.custom_xflickauthkey 
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

    try:
        data = response.json()
    except Exception:
        data = {"raw_response": response.text}

    company_doc.custom_webhook_delivery_logs = json.dumps(data, indent=2)
    company_doc.save(ignore_permissions=True)

    return data