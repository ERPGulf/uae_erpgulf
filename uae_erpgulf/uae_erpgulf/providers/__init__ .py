"""Provider registry.

This is the one place that turns a Provider name (as picked on E-Invoice
Provider Settings) into an actual adapter class. The mapping itself lives
in hooks.py (uae_einvoice_providers) - adding a new ASP is:

  1. write providers/<name>/adapter.py with a class subclassing BaseAdapter
  2. add one line to uae_einvoice_providers in hooks.py

No other file in the app needs to change.
"""

import frappe
from frappe import _


def _get_registry():
    """frappe.get_hooks() wraps hook values so multiple apps can each
    contribute one, without stepping on each other. For a plain dict hook
    like this one, that means each dotted-path value comes back wrapped in
    its own single-item list (e.g. {"Flick Network L.L.C": ["...FlickAdapter"]})
    instead of the plain string we actually want - so every value here gets
    unwrapped before use, not just the top-level raw result."""
    raw = frappe.get_hooks("uae_einvoice_providers")
    merged = {}

    def add(mapping):
        for key, value in mapping.items():
            if isinstance(value, list):
                value = value[-1] if value else None
            if value:
                merged[key] = value

    if isinstance(raw, dict):
        add(raw)
    elif isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict):
                add(entry)

    return merged


@frappe.whitelist()
def registered_providers():
    """Provider names that have an adapter registered in hooks.py
    (uae_einvoice_providers). Anything else cannot submit e-invoices.
    Whitelisted read-only so forms and scripts can read it."""
    return sorted(_get_registry().keys())


def assert_provider_registered(provider):
    """Throw a clear message when a provider name has no adapter."""
    if provider in _get_registry():
        return
    frappe.throw(
        _(
            "No adapter is registered for provider '{0}'. Providers with an adapter: {1}. "
            "Add one to uae_einvoice_providers in hooks.py (see the Multi-ASP Developer Guide)."
        ).format(provider, ", ".join(registered_providers()) or "none")
    )


def get_adapter(settings):
    """settings: an E-Invoice Provider Settings doc. Returns an adapter
    instance already bound to that row, ready to call .submit_invoice(...),
    .verify_auth(), etc. on."""
    registry = _get_registry()
    dotted_path = registry.get(settings.provider)

    if not dotted_path:
        frappe.throw(
            _(
                "No adapter is registered for provider '{0}'. "
                "Add it to uae_einvoice_providers in hooks.py."
            ).format(settings.provider)
        )

    adapter_class = frappe.get_attr(dotted_path)
    return adapter_class(settings)


COMPANY_PROVIDER_FIELD = "custom_accredited_service_providers"
SETTINGS_DOCTYPE = "E-Invoice Provider Settings"


def _merge_options(existing, names):
    lines = [l for l in (existing or "").split("\n")]
    missing = [n for n in names if n not in lines]
    if not missing:
        return None
    if lines and lines[0] != "":
        lines.insert(0, "")  # keep a blank first option
    return "\n".join(lines + missing)


def sync_provider_options():
    """Make every provider registered in hooks.py selectable.

    Runs after install and after migrate. Appends any registered provider
    name that is missing from the Company field's options (a Custom Field
    owned by this app) and from the Provider field on E-Invoice Provider
    Settings (via a Property Setter, so the DocType JSON is untouched).
    Existing options are never removed, so the full FTA list stays.
    A partner adding an adapter therefore only adds the folder and the
    hooks.py line, then runs bench migrate."""
    names = registered_providers()
    if not names:
        return

    cf_name = frappe.db.get_value("Custom Field", {"dt": "Company", "fieldname": COMPANY_PROVIDER_FIELD})
    if cf_name:
        cf = frappe.get_doc("Custom Field", cf_name)
        merged = _merge_options(cf.options, names)
        if merged is not None:
            cf.options = merged
            cf.save(ignore_permissions=True)

    from frappe.custom.doctype.property_setter.property_setter import make_property_setter

    df = frappe.get_meta(SETTINGS_DOCTYPE).get_field("provider")
    if df:
        merged = _merge_options(df.options, names)
        if merged is not None:
            make_property_setter(SETTINGS_DOCTYPE, "provider", "options", merged, "Text", validate_fields_for_doctype=False)

    frappe.clear_cache(doctype="Company")
    frappe.clear_cache(doctype=SETTINGS_DOCTYPE)
