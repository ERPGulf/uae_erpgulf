"""Shared helper for reading E-Invoice Provider Settings.

Every function that used to read Flick credentials off the Company doctype
(custom_base_url, custom_client_id, custom_xflickauthkey, ...) should go
through this instead. Nothing here is Flick-specific on purpose - the
Flick-only pieces (which header name to send, which URL paths) stay in
verify_token.py / webhook.py / etc. This file just answers "which settings
row is active for this company, and what's its base URL".
"""

import json

import frappe
from frappe import _

# Any key matching one of these (case-insensitive) gets blanked out before a
# response is ever saved to a field - applies to every provider's response,
# not just Flick's, since we can't know in advance what a new ASP's JSON
# will be called. This is what keeps "save the response for visibility"
# from quietly turning into "store secrets in the database".
_SENSITIVE_KEYS = {
	"secret", "webhook_secret", "client_secret", "api_secret",
	"access_token", "token", "api_key", "password",
}


def get_active_provider_settings(company):
	"""Return the enabled E-Invoice Provider Settings row for this company.

	Throws if none is enabled - every caller needs a real row to work with,
	so failing loudly here beats a confusing AttributeError further down.
	"""
	name = frappe.db.get_value(
		"E-Invoice Provider Settings",
		{"company": company, "enabled": 1},
		"name",
	)
	if not name:
		frappe.throw(
			_(
				"No enabled E-Invoice Provider Settings found for {0}. "
				"Create one and tick Enabled before submitting e-invoices."
			).format(company)
		)
	return frappe.get_doc("E-Invoice Provider Settings", name)


def get_settings_for_action(company=None, provider_settings=None):
	"""Resolve which E-Invoice Provider Settings row a button/action should
	run against.

	Prefer an explicit row (provider_settings, a docname) - that's what the
	Provider Settings form's OWN buttons pass, so Verify Token / Get
	Participant Details / Subscribe Webhook / etc always act on the exact
	row you're looking at, whether or not it's currently the enabled one
	for its company. Without this, those buttons would silently run
	against whatever OTHER row is currently active for that company
	instead - which is exactly the mix-up that happened when Verify Token
	on a disabled Marmin row ran Flick's check instead, because Flick was
	the enabled one at the time.

	Falls back to "the active enabled row for this company" only when no
	explicit row is given - that's the path Company's older buttons still
	use (company.js), since they only ever know a company name, never a
	specific row."""
	if provider_settings:
		return frappe.get_doc("E-Invoice Provider Settings", provider_settings)
	return get_active_provider_settings(company)


def get_base_url(settings):
	"""Base URL Override wins only if someone deliberately set it (an
	outlier). Otherwise the provider's normal Base URL."""
	return settings.base_url_override or settings.base_url


def _redact(value):
	"""Recursively blank out anything that looks like a secret."""
	if isinstance(value, dict):
		return {
			k: ("***redacted***" if k.lower() in _SENSITIVE_KEYS else _redact(v))
			for k, v in value.items()
		}
	if isinstance(value, list):
		return [_redact(v) for v in value]
	return value


def save_last_response(settings, fieldname, data):
	"""Save a redacted, pretty-printed copy of an API response onto this
	settings row, purely so it's visible on the form without needing to
	catch the popup or open bench console. This is display-only - nothing
	in the app ever reads these fields back, so it's fine if one is
	occasionally stale or missing. Deliberately NOT used for the Get Access
	Token response - that response body contains the actual bearer token,
	and no amount of redaction changes the fact that persisting it would
	defeat the entire point of keeping tokens out of the database."""
	if data is None:
		return
	try:
		redacted = _redact(data)
		text = redacted if isinstance(redacted, str) else json.dumps(redacted, indent=2)
		settings.db_set(fieldname, text)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "E-Invoice Response Log Error")
