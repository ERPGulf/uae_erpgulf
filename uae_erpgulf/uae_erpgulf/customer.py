import frappe

from uae_erpgulf.uae_erpgulf.provider_settings import get_active_provider_settings
from uae_erpgulf.uae_erpgulf.providers import get_adapter


@frappe.whitelist()
def custom_lookup_peppol_id_of_participant(company: str, peppol_id: str):
    """Lookup PEPPOL ID using whichever ASP this company is active on."""
    try:
        settings = get_active_provider_settings(company)
        return get_adapter(settings).lookup_peppol_id(peppol_id)

    except Exception as e:
        frappe.log_error(str(e), "PEPPOL Lookup Error")
        frappe.throw(str(e))
