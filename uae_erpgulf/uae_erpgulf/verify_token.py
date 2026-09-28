""" verify token"""
import json
import frappe
from frappe import _

from uae_erpgulf.uae_erpgulf.provider_settings import (
	get_active_provider_settings,
	get_settings_for_action,
	save_last_response,
)
from uae_erpgulf.uae_erpgulf.providers import get_adapter


def get_auth_headers(settings, extra=None):
	"""Kept for backward compatibility """
	return get_adapter(settings).get_auth_headers(extra)


@frappe.whitelist(allow_guest=False)
def verify_flick_token(company: str = None, provider_settings: str = None):
	"""Verify auth for a specific E-Invoice Provider Settings row """
	settings = get_settings_for_action(company, provider_settings)
	result = get_adapter(settings).verify_auth()

	if isinstance(result, dict):
		save_last_response(settings, "last_test_response", result.get("response"))

	return result


@frappe.whitelist(allow_guest=False)
def get_participant_details(company: str = None, provider_settings: str = None):
	"""Fetch participant details ."""
	settings = get_settings_for_action(company, provider_settings)
	result = get_adapter(settings).get_participant_details()

	if isinstance(result, dict):
		save_last_response(settings, "last_participant_response", result.get("response"))

	return result


@frappe.whitelist(allow_guest=False)
def get_flick_access_token(company: str = None, provider_settings: str = None):
	"""Fetch (or reuse the cached) OAuth2 access token for a specific row"""
	settings = get_settings_for_action(company, provider_settings)
	adapter = get_adapter(settings)
	token = adapter.get_valid_token()
	expiry = adapter.get_token_expiry()

	settings.db_set("last_access_token", token)
	if expiry:
		settings.db_set("token_expires_at", expiry)

	return {"access_token": token, "expires_at": str(expiry) if expiry else None}


def get_valid_flick_token(company):
	"""Return a valid access token for this company's active provider"""
	settings = get_active_provider_settings(company)
	return get_adapter(settings).get_valid_token()


@frappe.whitelist()
def get_document_status(invoice_name: str):
	"""Fetch document status from this company's active provider."""
	try:
		sales_invoice_doc = frappe.get_doc("Sales Invoice", invoice_name)
		settings = get_active_provider_settings(sales_invoice_doc.company)
		adapter = get_adapter(settings)

		result = adapter.get_document_status("Sales Invoice", sales_invoice_doc)

		
		if isinstance(result, dict) and "http_status" in result:
			http_status = result.get("http_status")
			body = result.get("response")
		else:
			
			http_status = None
			body = result

		
		sales_invoice_doc.db_set(
			"custom_document_status_response",
			json.dumps(body)
		)

		
		reporting_status = result.get("reporting_status") if isinstance(result, dict) else None
		if not reporting_status and isinstance(body, dict):
			data = body.get("data", {})
			reporting_status = data.get("reporting_status") or body.get("reporting_status")
		if reporting_status:
			sales_invoice_doc.db_set("custom_reporting_status", reporting_status)

		frappe.db.commit()  # nosemgrep: frappe-manual-commit

		return {"http_status": http_status, "response": body}

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "E-Invoice Document Status Error")
		frappe.throw(_("Failed to fetch document status: {0}").format(str(e)))