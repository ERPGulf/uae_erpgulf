import frappe
import requests
import json

@frappe.whitelist(allow_guest=True)
def flick_webhook_listener():
    data = frappe.request.get_data(as_text=True)

    frappe.log_error(
        title="Flick Webhook",
        message=data
    )

    return {"status": "success"}



@frappe.whitelist(allow_guest=True)
def register_flick_webhook(company):
    company_doc = frappe.get_doc("Company", company)
    base_url = company_doc.custom_base_url
    url = f"{base_url}/v1/webhooks/subscriptions"

    headers = {
        "Content-Type": "application/json",
        "X-Flick-Auth-Key": company_doc.custom_xflickauthkey # replace this
    }

    payload = {
        "name": "ERPNext Webhook",
        "endpoint": "https://uae.erpgulf.com/api/method/uae_erpgulf.uae_erpgulf.webhook.flick_webhook_listener",
        "event_types": [
            "document.received",
            "document.completed",
            "document.failed"
        ],
        "participant_ids": []
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

    headers = {
        "X-Flick-Auth-Key": company_doc.custom_xflickauthkey
    }

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

    headers = {
        "X-Flick-Auth-Key": company_doc.custom_xflickauthkey
    }

    response = requests.get(url, headers=headers)

    try:
        data = response.json()
    except Exception:
        data = {"raw_response": response.text}

    company_doc.custom_webhook_delivery_logs = json.dumps(response_data, indent=2)
    company_doc.save(ignore_permissions=True)

    return data