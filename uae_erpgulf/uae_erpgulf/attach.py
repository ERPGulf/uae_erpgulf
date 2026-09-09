import frappe
from frappe import _
from uae_erpgulf.uae_erpgulf.provider_settings import get_active_provider_settings
from uae_erpgulf.uae_erpgulf.providers import get_adapter
from frappe.utils.file_manager import save_file


@frappe.whitelist()
def get_document_xml(doctype: str, invoice_name: str):
    """Fetch the submitted document's XML from whichever ASP this company
    is active on, and save it against the Invoice."""
    try:
        doc = frappe.get_doc(doctype, invoice_name)
        settings = get_active_provider_settings(doc.company)
        adapter = get_adapter(settings)

        xml_data = adapter.get_document_xml(doctype, doc)

        if doc.custom_document_xml:
            old_file = frappe.get_all(
                "File",
                filters={"file_url": doc.custom_document_xml},
                fields=["name"]
            )
            if old_file:
                for f in old_file:
                    frappe.delete_doc("File", f.name, force=1)

        file_doc = save_file(
            fname=f"Submitted-XML-file {doc.name}.xml",
            content=xml_data,
            dt=doctype,
            dn=doc.name,
            is_private=1
        )

        doc.db_set("custom_document_xml", file_doc.file_url)
        frappe.db.commit()

        return {
            "status": "success",
            "file_url": file_doc.file_url
        }

    except Exception:
        frappe.log_error(frappe.get_traceback(), "E-Invoice XML Fetch Error")
        frappe.throw(_("Failed to fetch document XML"))


@frappe.whitelist()
def get_document_pdf(doctype: str, invoice_name: str):
    """Fetch the submitted document's PDF from whichever ASP this company
    is active on, and save it against the Invoice."""
    try:
        doc = frappe.get_doc(doctype, invoice_name)
        settings = get_active_provider_settings(doc.company)
        adapter = get_adapter(settings)

        pdf_data = adapter.get_document_pdf(doctype, doc)

        if doc.custom_document_pdf:
            old_file = frappe.get_all(
                "File",
                filters={"file_url": doc.custom_document_pdf},
                fields=["name"]
            )
            if old_file:
                frappe.delete_doc("File", old_file[0].name, force=1)

        file_doc = save_file(
            fname=f"Submitted-PDF-file {doc.name}.pdf",
            content=pdf_data,
            dt=doctype,
            dn=doc.name,
            is_private=1
        )

        doc.db_set("custom_document_pdf", file_doc.file_url)
        frappe.db.commit()

        return {
            "status": "success",
            "file_url": file_doc.file_url
        }

    except Exception:
        frappe.log_error(frappe.get_traceback(), "E-Invoice PDF Fetch Error")
        frappe.throw(_("Failed to fetch document PDF"))
