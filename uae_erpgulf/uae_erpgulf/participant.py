import requests
import frappe

def update_flick_participant(company, participant_id):
    """Updates participant details in Flick based on the Company document."""
    doc = frappe.get_doc("Company", company)

    base_url = doc.custom_base_url
    token = doc.custom_xflickauthkey  # or call your get_flick_token()

    url = f"{base_url}/v1/participants/{participant_id}"

    headers = {
        "Content-Type": "application/json",
        "X-Flick-Auth-Key": token
    }

    payload = {
        "trade_name": doc.company_name,
        "legal_name": doc.company_name,
        "peppol_id": doc.custom_peppol_id,
        "street_address": doc.custom_street_address,
        "additional_street_address": doc.custom_additional_street,
        "additional_address_lines": doc.custom_additional_address,
        "city_address": doc.custom_city,
        "postal_zone": doc.custom_postal_code,
        "emirates_code": doc.custom_emirate_code,
        "country_code": doc.custom_country_code or "AE",
        "identifiers": [
            {
                "scheme_id": "AE:TL",
                "value": doc.tax_id
            }
        ],
        "contact_name": doc.custom_contact_name,
        "contact_telephone": doc.custom_contact_phone,
        "contact_email": doc.custom_contact_email,
        "fz_beneficiary_id": doc.custom_fz_id
    }

    try:
        response = requests.put(url, headers=headers, json=payload)
        response.raise_for_status()

        return response.json()

    except requests.exceptions.RequestException as e:
        frappe.log_error(frappe.get_traceback(), "Flick Participant Update Error")
        return {
            "status": "error",
            "message": str(e),
            "response": getattr(e.response, "text", "")
        }