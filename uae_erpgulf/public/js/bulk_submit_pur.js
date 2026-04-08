// Utility function to extend existing listview events
function extend_listview_event(doctype, event, callback) {

    if (!frappe.listview_settings[doctype]) {
        frappe.listview_settings[doctype] = {};
    }

    const old_event = frappe.listview_settings[doctype][event];

    frappe.listview_settings[doctype][event] = function (listview) {

        if (old_event) {
            old_event(listview);
        }

        callback(listview);
    };
}


// Extend Sales Invoice ListView
extend_listview_event("Purchase Invoice", "onload", function (listview) {

    console.log("FTA Bulk Submission Script Loaded");

    listview.page.add_action_item(
        __("Send Invoices to FTA Submission"),
        function () {

            const selected = listview.get_checked_items();

            if (!selected.length) {
                frappe.msgprint(__('Please select at least one Sales Invoice.'));
                return;
            }

            // Optional: require more than one invoice
            if (selected.length < 2) {
                frappe.msgprint(__('Please select more than one invoice.'));
                return;
            }

            let invoice_names = selected.map(d => d.name);

            frappe.call({
                method: "uae_erpgulf.uae_erpgulf.send_purchase.bulk_send_invoices",
                args: {
                    invoices: invoice_names
                },
                freeze: true,
                freeze_message: __("Submitting Invoices to FTA..."),

                callback: function (r) {

                    if (!r.message) {
                        frappe.msgprint(__('Server did not return a response.'));
                        return;
                    }

                    let msg = "";

                    // if (r.message.success && r.message.success.length) {
                    //     msg += "<b>Submitted Successfully:</b><br>" +
                    //         r.message.success.join("<br>") + "<br><br>";
                    // }

                    if (r.message.skipped && r.message.skipped.length) {
                        msg += "<b>Skipped (Already Submitted):</b><br>" +
                            r.message.skipped.join("<br>") + "<br><br>";
                    }

                    if (r.message.failed && r.message.failed.length) {
                        msg += "<b>Failed:</b><br>" +
                            r.message.failed.join("<br>");
                    }

                    frappe.msgprint(msg || __("No invoices processed."));

                    // Refresh list
                    listview.refresh();

                    // Uncheck rows
                    listview.check_all(false);
                }
            });

        }
    );

    console.log('Custom "Send Invoices to FTA Submission" action added.');
});