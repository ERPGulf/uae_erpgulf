import frappe

from uae_erpgulf.uae_erpgulf.provider_settings import get_active_provider_settings
from uae_erpgulf.uae_erpgulf.providers import get_adapter


def update_flick_participant(company, participant_id):
    """Updates participant details with whichever ASP this company is
    active on. `participant_id` is accepted for backward compatibility
    with existing callers, but each adapter reads the Participant ID off
    the settings row itself rather than trusting the argument."""
    doc = frappe.get_doc("Company", company)
    settings = get_active_provider_settings(company)
    return get_adapter(settings).update_participant(doc)
