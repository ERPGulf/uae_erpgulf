frappe.ui.form.on("Company", {

    custom_verify_token_: function (frm) {
        console.log("Button clicked – script loaded!");

        frappe.call({
            method: "uae_erpgulf.uae_erpgulf.verify_token.verify_flick_token",
            args: { company: frm.doc.name },
            callback: function (r) {
                console.log("Server Response:", r);

                if (r.message?.status === "success") {
                    frappe.msgprint("✔ Token Verified Successfully<br><br>" + r.message.response);
                } else {
                    frappe.msgprint("❌ Error: " + r.message?.message);
                }

                frm.reload_doc();
            }
        });
    },

    custom_get_participant_details: function (frm) {

        if (!frm.doc.custom_participant_id) {
            frappe.msgprint("Please enter Participant ID");
            return;
        }

        frappe.call({
            method: "uae_erpgulf.uae_erpgulf.verify_token.get_participant_details",
            args: {
                company: frm.doc.name
            },
            callback: function (r) {

                console.log("Participant Response:", r);

                if (r.message?.status === "success") {
                    frappe.msgprint(
                        "✔ Participant details fetched successfully<br><br>" +
                        JSON.stringify(r.message.response, null, 2)
                    );
                } else {
                    frappe.msgprint("❌ Failed to fetch participant details");
                }

                frm.reload_doc();
            }
        });

    },

    // ✅ FIXED: Now inside same object
    custom_get_access_token: function (frm) {

        if (!frm.doc.custom_client_id || !frm.doc.custom_client_secret) {
            frappe.msgprint("Please set Client ID and Client Secret");
            return;
        }

        frappe.call({
            method: "uae_erpgulf.uae_erpgulf.verify_token.get_flick_access_token",
            args: {
                company: frm.doc.name
            },
            freeze: true,
            freeze_message: "Fetching Access Token...",

            callback: function (r) {
                console.log("Access Token Response:", r);

                if (r.message) {
                    frappe.msgprint({
                        title: "Success",
                        message:
                            "✔ Access Token Generated & Saved Successfully<br><br>" +
                            "<pre>" + JSON.stringify(r.message, null, 2) + "</pre>",
                        indicator: "green"
                    });
                } else {
                    frappe.msgprint("❌ Failed to fetch access token");
                }

                frm.reload_doc();
            },

            error: function (err) {
                console.error(err);
                frappe.msgprint("❌ Error while fetching access token");
            }
        });
    }

});
frappe.ui.form.on('Company', {

    custom_subscribe_webhook: function (frm) {

        frappe.call({
            method: "uae_erpgulf.uae_erpgulf.webhook.register_flick_webhook",
            args: {
                company: frm.doc.name
            },
            freeze: true,
            freeze_message: "Subscribing Webhook...",

            callback: function (r) {
                console.log("Webhook Response:", r);

                if (r.message) {
                    frappe.msgprint({
                        title: "Success",
                        message:
                            "✔ Webhook Subscribed Successfully<br><br>" +
                            "<pre>" + JSON.stringify(r.message, null, 2) + "</pre>",
                        indicator: "green"
                    });
                } else {
                    frappe.msgprint("❌ Failed to subscribe webhook");
                }

                frm.reload_doc();
            },

            error: function (err) {
                console.error(err);
                frappe.msgprint("❌ Error while subscribing webhook");
            }
        });
    },

    // ✅ Get Subscription
    custom_get_subscription: function (frm) {

        frappe.call({
            method: "uae_erpgulf.uae_erpgulf.webhook.custom_get_subscription",
            args: {
                company: frm.doc.name
            },
            freeze: true,
            freeze_message: "Fetching Webhook Details...",

            callback: function (r) {
                console.log("Get Webhook Response:", r);

                if (r.message) {
                    frappe.msgprint({
                        title: "Webhook Details",
                        message:
                            "📡 Webhook Fetched Successfully<br><br>" +
                            "<pre>" + JSON.stringify(r.message, null, 2) + "</pre>",
                        indicator: "blue"
                    });
                } else {
                    frappe.msgprint("❌ Failed to fetch webhook details");
                }

                frm.reload_doc();
            },

            error: function (err) {
                console.error(err);
                frappe.msgprint("❌ Error while fetching webhook details");
            }
        });
    },

    // ✅ NEW: Webhook Logs (Deliveries)
    custom_webhook_logs: function (frm) {

        if (!frm.doc.custom_uuid_of_webhook) {
            frappe.msgprint("⚠ Please create webhook first");
            return;
        }

        frappe.call({
            method: "uae_erpgulf.uae_erpgulf.webhook.get_webhook_deliveries",
            args: {
                company: frm.doc.name
            },
            freeze: true,
            freeze_message: "Fetching Webhook Logs...",

            callback: function (r) {
                console.log("Webhook Logs:", r);

                if (r.message) {
                    frappe.msgprint({
                        title: "📜 Webhook Delivery Logs",
                        message:
                            "<pre>" + JSON.stringify(r.message, null, 2) + "</pre>",
                        indicator: "orange"
                    });
                } else {
                    frappe.msgprint("❌ Failed to fetch webhook logs");
                }
            },

            error: function (err) {
                console.error(err);
                frappe.msgprint("❌ Error while fetching webhook logs");
            }
        });
    }

});