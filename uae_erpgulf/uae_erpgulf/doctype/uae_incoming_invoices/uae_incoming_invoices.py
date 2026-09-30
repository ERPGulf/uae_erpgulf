# Copyright (c) 2026, erpgulf.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class UAEIncomingInvoices(Document):
    def before_naming(self):
        self.title = self.document_id

    def validate(self):
        self.title = self.document_id