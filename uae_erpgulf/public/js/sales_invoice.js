frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {

        frm.clear_custom_buttons(); // IMPORTANT for v16

        if (frm.doc.docstatus === 0 || frm.doc.docstatus === 1) {

            frm.add_custom_button(
                __("Send Invoice"),
                () => {

                    frm.call({
                        method: "uae_erpgulf.uae_erpgulf.json_einvoice.send_invoice_json",
                        args: {
                            invoice_number: frm.doc.name
                        },
                        freeze: true,
                        freeze_message: __("Generating and attaching invoice JSON..."),
                        callback(r) {
                            if (!r.exc) {
                                frappe.msgprint(__("Invoice JSON generated and attached"));
                                frm.reload_doc();
                            }
                        }
                    });

                },
                __("UAE E-Invoice")
            );
        }
    }
});
