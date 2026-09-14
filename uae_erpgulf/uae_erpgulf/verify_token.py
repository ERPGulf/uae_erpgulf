# import json

# import frappe
# from frappe import _

# from uae_erpgulf.uae_erpgulf.provider_settings import (
# 	get_active_provider_settings,
# 	get_settings_for_action,
# 	save_last_response,
# )
# from uae_erpgulf.uae_erpgulf.providers import get_adapter


# def get_auth_headers(settings, extra=None):
# 	"""Kept for backward compatibility - other files still import this
# 	name. All it does now is resolve the right adapter for this settings
# 	row and ask it to build headers - the actual header logic (which
# 	header name, oauth2 vs api_key, ...) lives in that provider's own
# 	adapter, not here.
# 	"""
# 	return get_adapter(settings).get_auth_headers(extra)


# @frappe.whitelist(allow_guest=False)
# def verify_flick_token(company: str = None, provider_settings: str = None):
# 	"""Verify auth for a specific E-Invoice Provider Settings row when one
# 	is given (that's what the Provider Settings form's own button passes -
# 	see e_invoice_provider_settings.js), otherwise falls back to the active
# 	enabled row for the given company (older Company-button callers).
# 	Records the result on that row's Last Test Status / Last Test On /
# 	Last Test Response - always the row actually being tested, not
# 	whichever row happens to be enabled elsewhere for the same company."""
# 	settings = get_settings_for_action(company, provider_settings)
# 	result = get_adapter(settings).verify_auth()

# 	if isinstance(result, dict):
# 		save_last_response(settings, "last_test_response", result.get("response"))

# 	return result


# @frappe.whitelist(allow_guest=False)
# def get_participant_details(company: str = None, provider_settings: str = None):
# 	"""Fetch participant details for a specific row when one is given,
# 	otherwise the active provider for the given company. Saves a copy on
# 	Last Participant Response so it's visible on the form."""
# 	settings = get_settings_for_action(company, provider_settings)
# 	result = get_adapter(settings).get_participant_details()

# 	if isinstance(result, dict):
# 		save_last_response(settings, "last_participant_response", result.get("response"))

# 	return result


# @frappe.whitelist(allow_guest=False)
# def get_flick_access_token(company: str = None, provider_settings: str = None):
# 	"""Fetch (or reuse the cached) OAuth2 access token for a specific row
# 	when one is given, otherwise the active provider for the given company.
# 	Redis cache stays the source of truth this app actually relies on (see
# 	get_valid_flick_token) - this also saves a copy on Last Access Token and
# 	Token Expires At purely so they're visible on the form. Since Redis
# 	silently refreshes both on its own whenever the token expires, treat
# 	these fields as "the last one that was fetched", not "the one currently
# 	in use" - they won't auto-update the next time a different function
# 	refreshes the real cached token in the background."""
# 	settings = get_settings_for_action(company, provider_settings)
# 	adapter = get_adapter(settings)
# 	token = adapter.get_valid_token()
# 	expiry = adapter.get_token_expiry()

# 	settings.db_set("last_access_token", token)
# 	if expiry:
# 		settings.db_set("token_expires_at", expiry)

# 	return {"access_token": token, "expires_at": str(expiry) if expiry else None}


# def get_valid_flick_token(company):
# 	"""Return a valid access token for this company's active provider,
# 	refreshing if needed. Only meaningful when that provider/row uses
# 	OAuth2 - kept under this name for backward compatibility with older
# 	callers, but it now works for any OAuth2-based adapter, not just Flick."""
# 	settings = get_active_provider_settings(company)
# 	return get_adapter(settings).get_valid_token()


# @frappe.whitelist()
# def get_document_status(invoice_name: str):
# 	"""Fetch document status from this company's active provider and save
# 	the response on the Sales Invoice."""
# 	try:
# 		sales_invoice_doc = frappe.get_doc("Sales Invoice", invoice_name)
# 		settings = get_active_provider_settings(sales_invoice_doc.company)
# 		adapter = get_adapter(settings)

# 		result = adapter.get_document_status("Sales Invoice", sales_invoice_doc)

# 		# Both adapters now always return {"http_status": <int>, "response":
# 		# <body>} from get_document_status - success or failure - instead of
# 		# either the bare body or throwing on a bad HTTP status. That's what
# 		# lets the "Get Document Status" button in sales_invoice.js show the
# 		# real status code and pick its own colour (red for a genuine
# 		# non-2xx, not just orange for "no reporting_status yet"), instead
# 		# of a failure escaping as Frappe's own generic red error dialog.
# 		if isinstance(result, dict) and "http_status" in result:
# 			http_status = result.get("http_status")
# 			body = result.get("response")
# 		else:
# 			# Shouldn't happen now both adapters always envelope their
# 			# response, but kept as a safety net rather than crashing on an
# 			# unexpected shape from some future adapter.
# 			http_status = None
# 			body = result

# 		# Always save whatever came back, regardless of shape - this used to
# 		# only save/extract when the body was a dict with a "data" key
# 		# (Flick's shape: {"data": {"reporting_status": ...}}). Marmin's
# 		# peppol-status-logs endpoint doesn't have a confirmed docs page for
# 		# its response shape yet (may well be a flat dict, or a list/log of
# 		# entries, given the endpoint name) - under the old check, a Marmin
# 		# response failing that isinstance/"data" test meant clicking "Get
# 		# Document Status" silently saved nothing at all. Now the raw body
# 		# is always saved, and reporting_status is only pulled out when the
# 		# shape actually looks like it has one (nested under "data", the
# 		# same way Flick's does, or flat at the top level, the same
# 		# fallback pattern already used for the submit response elsewhere
# 		# in this app) - never assumed for a shape we haven't confirmed
# 		# yet, like a bare list.
# 		sales_invoice_doc.db_set(
# 			"custom_document_status_response",
# 			json.dumps(body)
# 		)

# 		reporting_status = None
# 		if isinstance(body, dict):
# 			data = body.get("data", {})
# 			reporting_status = data.get("reporting_status") or body.get("reporting_status")
# 		if reporting_status:
# 			sales_invoice_doc.db_set("custom_reporting_status", reporting_status)

# 		frappe.db.commit()  # nosemgrep: frappe-manual-commit

# 		return {"http_status": http_status, "response": body}

# 	except Exception as e:
# 		frappe.log_error(frappe.get_traceback(), "E-Invoice Document Status Error")
# 		frappe.throw(_("Failed to fetch document status: {0}").format(str(e)))

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
	get_valid_flick_token) - this also saves a copy on Last Access Token and
	Token Expires At purely so they're visible on the form. Since Redis
	silently refreshes both on its own whenever the token expires, treat
	these fields as "the last one that was fetched", not "the one currently
	in use" - they won't auto-update the next time a different function
	refreshes the real cached token in the background."""
	settings = get_settings_for_action(company, provider_settings)
	adapter = get_adapter(settings)
	token = adapter.get_valid_token()
	expiry = adapter.get_token_expiry()

	settings.db_set("last_access_token", token)
	if expiry:
		settings.db_set("token_expires_at", expiry)

	return {"access_token": token, "expires_at": str(expiry) if expiry else None}


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

		result = adapter.get_document_status("Sales Invoice", sales_invoice_doc)

		# Both adapters now always return {"http_status": <int>, "response":
		# <body>} from get_document_status - success or failure - instead of
		# either the bare body or throwing on a bad HTTP status. That's what
		# lets the "Get Document Status" button in sales_invoice.js show the
		# real status code and pick its own colour (red for a genuine
		# non-2xx, not just orange for "no reporting_status yet"), instead
		# of a failure escaping as Frappe's own generic red error dialog.
		if isinstance(result, dict) and "http_status" in result:
			http_status = result.get("http_status")
			body = result.get("response")
		else:
			# Shouldn't happen now both adapters always envelope their
			# response, but kept as a safety net rather than crashing on an
			# unexpected shape from some future adapter.
			http_status = None
			body = result

		# Always save whatever came back, regardless of shape - this used to
		# only save/extract when the body was a dict with a "data" key
		# (Flick's shape: {"data": {"reporting_status": ...}}). Marmin's
		# peppol-status-logs endpoint doesn't have a confirmed docs page for
		# its response shape yet (may well be a flat dict, or a list/log of
		# entries, given the endpoint name) - under the old check, a Marmin
		# response failing that isinstance/"data" test meant clicking "Get
		# Document Status" silently saved nothing at all. Now the raw body
		# is always saved, and reporting_status is only pulled out when the
		# shape actually looks like it has one (nested under "data", the
		# same way Flick's does, or flat at the top level, the same
		# fallback pattern already used for the submit response elsewhere
		# in this app) - never assumed for a shape we haven't confirmed
		# yet, like a bare list.
		sales_invoice_doc.db_set(
			"custom_document_status_response",
			json.dumps(body)
		)

		# An adapter can put its own derived reporting_status straight into
		# the envelope alongside http_status/response - Marmin's does this
		# (see MarminAdapter._reporting_status_from_status_logs), since its
		# body is a plain event-log list with no status field of its own
		# to read the way Flick's {"data": {"reporting_status": ...}}
		# shape has. Prefer that if the adapter supplied one; otherwise
		# fall back to sniffing the body itself for Flick's shape.
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