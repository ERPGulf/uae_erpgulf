"""this file contains the functions to validations."""
import frappe
from frappe import _

def validate_accredited_service_provider(doc, method=None):
    """Runs before a Sales/Purchase Invoice is submitted. """
    company_doc = frappe.get_doc("Company", doc.company)

    if not company_doc.custom_uae_einvoice_enabled:
        return

    provider = company_doc.custom_accredited_service_providers
    if not provider:
        frappe.throw(_(
            "Select an Accredited Service Provider on {0} before submitting e-invoices."
        ).format(doc.company))

    has_settings = frappe.db.exists(
        "E-Invoice Provider Settings",
        {"company": doc.company, "provider": provider, "enabled": 1},
    )
    if not has_settings:
        frappe.throw(_(
            "No enabled E-Invoice Provider Settings found for {0} under {1}. "
            "Set up its credentials before submitting e-invoices."
        ).format(provider, doc.company))

  
def success_log(
    title=None,
    document_id=None,
    participant_id=None,
    invoice_number=None,
    reporting_status=None,
    exchange_status=None,
    status=None,
    submit_response=None,
):
    """Create UAE E-invoicing success log"""

    try:
        log = frappe.get_doc(
            {
                "doctype": "UAE E-invoicing success log",
                "title":  "UAE E-Invoice Submitted Successfully",
                "document_id": document_id,
                "participant_id": participant_id,
                "invoice_number": invoice_number,
                "reporting_status": reporting_status,
                "exchange_status": exchange_status,
                "status": status,
                "submit_response": (
                    frappe.as_json(submit_response)
                    if isinstance(submit_response, (dict, list))
                    else submit_response
                ),
            }
        )

        log.insert(ignore_permissions=True)
        frappe.db.commit()

        return log.name

    except (
        ValueError,
        TypeError,
        KeyError,
        frappe.ValidationError,
    ) as e:
        frappe.log_error(
            title="UAE E-invoicing Success Log Error",
            message=frappe.get_traceback(),
        )

        frappe.throw(_("Error in UAE success log: {0}").format(str(e)))