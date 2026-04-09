frappe.ui.form.on("Purchase Invoice", {
    refresh(frm) {

        frm.clear_custom_buttons();

        // Show button if:
        // 1. Submitted
        // 2. UAE status is Not Submitted OR Failed

        if (
            frm.doc.docstatus === 1 &&
            (
                frm.doc.custom_uae_einvoice_status === "Not Submitted" ||
                frm.doc.custom_reporting_status === "failed"
            )
        ) {

            frm.add_custom_button(
                __("Send Invoice"),
                () => {

                    frm.call({
                        method: "uae_erpgulf.uae_erpgulf.send_purchase.generate_and_send_einvoice",
                        args: {
                            doc: frm.doc
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

frappe.ui.form.on("Purchase Invoice", {
    refresh: function (frm) {

        if (!frm.doc.__islocal) {

            frm.add_custom_button(__('Get Document Status'), function () {

                frappe.call({
                    method: "uae_erpgulf.uae_erpgulf.send_purchase.get_document_status",
                    args: {
                        invoice_name: frm.doc.name
                    },
                    freeze: true,
                    freeze_message: __("Checking Flick Document Status..."),
                    callback: function (r) {

                        if (r.message) {

                            frappe.msgprint({
                                title: __("Flick Response"),
                                message: `<pre>${JSON.stringify(r.message, null, 2)}</pre>`,
                                indicator: "green"
                            });

                        }

                    }
                });

            });

        }
    }
});