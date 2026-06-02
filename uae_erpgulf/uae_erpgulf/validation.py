
import frappe
from frappe import _

def validate_accredited_service_provider(doc, method=None):
    company_doc = frappe.get_doc("Company", doc.company)

    if (
        company_doc.custom_base_url
        and "flick.network" in company_doc.custom_base_url.lower()
        and company_doc.custom_accredited_service_providers != "Flick Network L.L.C"
    ):
        frappe.throw(_(
            "Selected Accredited Service Provider must be Flick Network L.L.C for flick api integration."
        ))



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