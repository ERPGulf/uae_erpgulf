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
