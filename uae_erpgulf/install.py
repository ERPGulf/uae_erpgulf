import frappe
from frappe import _


def refuse_new_install():
    frappe.throw(
        _(
            "Most UAE companies do business internationally, so their ERPNext instances "
            "usually cover more than one country, Oman in particular. Many users asked us "
            "to accommodate this, so we have released a new app, einvoice_erpgulf, that "
            "handles multiple countries and providers in one install. Please install it "
            "from https://github.com/ERPGulf/einvoice_erpgulf instead of this one. "
            "This repository will be archived soon."
        ),
        title=_("uae_erpgulf has been superseded"),
    )