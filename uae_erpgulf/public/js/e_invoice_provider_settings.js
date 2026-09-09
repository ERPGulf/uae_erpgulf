// Replaces the "Verify Token" / "Get Access Token" / "Subscribe Webhook" /
// "Get Subscription" / "Webhook Logs" buttons that used to live on Company
// (see company.js) - now that credentials and webhook_uuid/secret live on
// this row instead of Company, these buttons live here too. They call the
// exact same server methods Company's buttons called (nothing changed on
// the Python side) - just with frm.doc.company instead of frm.doc.name,
// since this form's "company" field is the one those methods expect.
//
// No custom Button fields needed on this doctype for this - these are
// added directly to the toolbar in refresh(), same as any custom button.

frappe.ui.form.on("E-Invoice Provider Settings", {
    refresh: function (frm) {
        if (frm.is_new()) {
            return;
        }

        function show_json(title, response) {
            const pretty = JSON.stringify(response, null, 2);
            frappe.msgprint({
                title: __(title),
                message: `<pre style="white-space:pre-wrap;background:#f6f8fa;padding:12px;
                    border-radius:6px;max-height:400px;overflow:auto;font-size:12px;">${frappe.utils.escape_html(pretty)}</pre>`,
                wide: true
            });
        }

        frm.add_custom_button(__("Verify Token"), function () {
            frappe.call({
                method: "uae_erpgulf.uae_erpgulf.verify_token.verify_flick_token",
                args: { company: frm.doc.company, provider_settings: frm.doc.name },
                freeze: true,
                freeze_message: __("Verifying..."),
                callback: function (r) {
                    show_json("Verify Result", r.message);
                    frm.reload_doc();
                }
            });
        }, __("E-Invoicing"));

        frm.add_custom_button(__("Get Participant Details"), function () {
            frappe.call({
                method: "uae_erpgulf.uae_erpgulf.verify_token.get_participant_details",
                args: { company: frm.doc.company, provider_settings: frm.doc.name },
                freeze: true,
                freeze_message: __("Fetching..."),
                callback: function (r) {
                    show_json("Participant Details", r.message);
                }
            });
        }, __("E-Invoicing"));

        frm.add_custom_button(__("Get Access Token"), function () {
            frappe.call({
                method: "uae_erpgulf.uae_erpgulf.verify_token.get_flick_access_token",
                args: { company: frm.doc.company, provider_settings: frm.doc.name },
                freeze: true,
                freeze_message: __("Fetching Access Token..."),
                callback: function (r) {
                    frappe.msgprint({
                        title: __("Access Token"),
                        message: r.message && r.message.access_token
                            ? __("Access token fetched, cached, and saved to Last Access Token.")
                            : __("Failed to fetch access token"),
                        indicator: r.message && r.message.access_token ? "green" : "red"
                    });
                    frm.reload_doc();
                }
            });
        }, __("E-Invoicing"));

        frm.add_custom_button(__("Subscribe Webhook"), function () {
            frappe.call({
                method: "uae_erpgulf.uae_erpgulf.webhook.register_flick_webhook",
                args: { company: frm.doc.company, provider_settings: frm.doc.name },
                freeze: true,
                freeze_message: __("Subscribing Webhook..."),
                callback: function (r) {
                    show_json("Webhook Subscribed", r.message);
                    frm.reload_doc();
                }
            });
        }, __("E-Invoicing"));

        frm.add_custom_button(__("Get Subscription"), function () {
            frappe.call({
                method: "uae_erpgulf.uae_erpgulf.webhook.custom_get_subscription",
                args: { company: frm.doc.company, provider_settings: frm.doc.name },
                freeze: true,
                freeze_message: __("Fetching Subscription..."),
                callback: function (r) {
                    show_json("Webhook Subscription", r.message);
                }
            });
        }, __("E-Invoicing"));

        frm.add_custom_button(__("Webhook Logs"), function () {
            if (!frm.doc.webhook_uuid) {
                frappe.msgprint(__("Subscribe the webhook first."));
                return;
            }
            frappe.call({
                method: "uae_erpgulf.uae_erpgulf.webhook.get_webhook_deliveries",
                args: { company: frm.doc.company, provider_settings: frm.doc.name },
                freeze: true,
                freeze_message: __("Fetching Webhook Logs..."),
                callback: function (r) {
                    show_json("Webhook Delivery Logs", r.message);
                }
            });
        }, __("E-Invoicing"));
    }
});
