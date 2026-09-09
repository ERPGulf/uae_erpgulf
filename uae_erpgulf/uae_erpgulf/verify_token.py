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
	"""Kept for backward compatibility - other files still import this
	name. All it does now is resolve the right adapter for this settings
	row and ask it to build headers - the actual header logic (which
	header name, oauth2 vs api_key, ...) lives in that provider's own
	adapter, not here.
	"""
	return get_adapter(settings).get_auth_headers(extra)


@frappe.whitelist(allow_guest=False)
def verify_flick_token(company: str = None, provider_settings: str = None):
	"""Verify auth for a specific E-Invoice Provider Settings row when one
	is given (that's what the Provider Settings form's own button passes -
	see e_invoice_provider_settings.js), otherwise falls back to the active
	enabled row for the given company (older Company-button callers).
	Records the result on that row's Last Test Status / Last Test On /
	Last Test Response - always the row actually being tested, not
	whichever row happens to be enabled elsewhere for the same company."""
	settings = get_settings_for_action(company, provider_settings)
	result = get_adapter(settings).verify_auth()

	if isinstance(result, dict):
		save_last_response(settings, "last_test_response", result.get("response"))

	return result


@frappe.whitelist(allow_guest=False)
def get_participant_details(company: str = None, provider_settings: str = None):
	"""Fetch participant details for a specific row when one is given,
	otherwise the active provider for the given company. Saves a copy on
	Last Participant Response so it's visible on the form."""
	settings = get_settings_for_action(company, provider_settings)
	result = get_adapter(settings).get_participant_details()

	if isinstance(result, dict):
		save_last_response(settings, "last_participant_response", result.get("response"))

	return result


@frappe.whitelist(allow_guest=False)
def get_flick_access_token(company: str = None, provider_settings: str = None):
	"""Fetch (or reuse the cached) OAuth2 access token for a specific row
	when one is given, otherwise the active provider for the given company.
	Redis cache stays the source of truth this app actually relies on (see
	get_valid_flick_token) - this also saves a copy on Last Access Token
	purely so it's visible on the form. Since Redis silently refreshes this
	token on its own whenever it expires, treat this field as "the last one
	that was fetched", not "the one currently in use" - it won't
	auto-update itself the next time a different function refreshes the
	real cached token in the background."""
	settings = get_settings_for_action(company, provider_settings)
	token = get_adapter(settings).get_valid_token()

	settings.db_set("last_access_token", token)

	return {"access_token": token}


def get_valid_flick_token(company):
	"""Return a valid access token for this company's active provider,
	refreshing if needed. Only meaningful when that provider/row uses
	OAuth2 - kept under this name for backward compatibility with older
	callers, but it now works for any OAuth2-based adapter, not just Flick."""
	settings = get_active_provider_settings(company)
	return get_adapter(settings).get_valid_token()


@frappe.whitelist()
def get_document_status(invoice_name: str):
	"""Fetch document status from this company's active provider and save
	the response on the Sales Invoice."""
	try:
		sales_invoice_doc = frappe.get_doc("Sales Invoice", invoice_name)
		settings = get_active_provider_settings(sales_invoice_doc.company)
		adapter = get_adapter(settings)

		response_json = adapter.get_document_status("Sales Invoice", sales_invoice_doc)

		if isinstance(response_json, dict) and response_json.get("data"):
			data = response_json.get("data", {})
			reporting_status = data.get("reporting_status")
			sales_invoice_doc.db_set(
				"custom_document_status_response",
				json.dumps(response_json)
			)
			if reporting_status:
				sales_invoice_doc.db_set("custom_reporting_status", reporting_status)

		return response_json

	except Exception:
		frappe.log_error(frappe.get_traceback(), "E-Invoice Document Status Error")
		frappe.throw(_("Failed to fetch document status"))
