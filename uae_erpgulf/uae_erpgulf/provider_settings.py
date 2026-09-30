"""Shared helper for reading E-Invoice Provider Settings."""

import json
import frappe
from frappe import _

# from quietly turning into "store secrets in the database".
_SENSITIVE_KEYS = {
	"secret", "webhook_secret", "client_secret", "api_secret",
	"access_token", "token", "api_key", "password",
}


def get_active_provider_settings(company):
	"""Return the E-Invoice Provider Settings company actually"""
	provider = frappe.db.get_value("Company", company, "custom_accredited_service_providers")
	if not provider:
		frappe.throw(
			_(
				"Select an Accredited Service Provider on {0} (UAE E-invoicing tab) "
				"before submitting e-invoices."
			).format(company)
		)

	name = frappe.db.get_value(
		"E-Invoice Provider Settings",
		{"company": company, "provider": provider, "enabled": 1},
		"name",
	)
	if not name:
		frappe.throw(
			_(
				"No enabled E-Invoice Provider Settings found for {0} under {1}. "
				"Create one (or tick Enabled on the existing row) before submitting "
				"e-invoices."
			).format(provider, company)
		)
	return frappe.get_doc("E-Invoice Provider Settings", name)


def get_settings_for_action(company=None, provider_settings=None):
	"""Resolve which E-Invoice Provider Settings row a button"""
	if provider_settings:
		return frappe.get_doc("E-Invoice Provider Settings", provider_settings)
	return get_active_provider_settings(company)


def get_base_url(settings):
	"""Base URL Override wins only if someone deliberately set it"""
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
	"""Save a redacted, pretty-printed copy of an API response """
	if data is None:
		return
	try:
		redacted = _redact(data)
		text = redacted if isinstance(redacted, str) else json.dumps(redacted, indent=2)
		settings.db_set(fieldname, text)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "E-Invoice Response Log Error")