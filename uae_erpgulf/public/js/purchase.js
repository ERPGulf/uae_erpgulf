
frappe.ui.form.on("Purchase Invoice", {
    refresh(frm) {

        frm.clear_custom_buttons();

        // Show button only if:
        // 1. Invoice is Submitted (docstatus = 1)
        // 2. UAE status is "Not Submitted"

        if (
            frm.doc.docstatus === 1 &&
            frm.doc.custom_uae_einvoice_status === "Not Submitted"
        ) {

            frm.add_custom_button(
                __("Send Invoice"),
                () => {

                    frm.call({
                        method: "uae_erpgulf.uae_erpgulf.test.generate_and_send_einvoice",
                        args: {
                            doc: frm.doc   // 🔥 IMPORTANT
                        },
                        freeze: true,
                        freeze_message: __("Generating and sending UAE E-Invoice..."),
                        callback(r) {
                            if (!r.exc) {
                                frappe.msgprint(__("UAE E-Invoice processed successfully"));
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