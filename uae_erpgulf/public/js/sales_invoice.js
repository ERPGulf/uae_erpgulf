frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {

        frm.clear_custom_buttons();
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
                        method: "uae_erpgulf.uae_erpgulf.test.generate_and_send_einvoice",
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
frappe.ui.form.on("Sales Invoice", {
    refresh: function (frm) {
        if (!frm.doc.__islocal && frm.doc.custom_uae_einvoice_status !== "Not Submitted") {

            // Hide Get Document Status once reported
            const is_reported = (frm.doc.custom_reporting_status || "").toLowerCase() === "reported";

            if (!is_reported) {
                frm.add_custom_button(__('Get Document Status'), function () {
                    frappe.call({
                        method: "uae_erpgulf.uae_erpgulf.verify_token.get_document_status",
                        args: {
                            invoice_name: frm.doc.name
                        },
                        freeze: true,
                        freeze_message: __("Checking Document Status..."),
                        callback: function (r) {
                            if (r.message) {
                                const envelope = r.message;
                                const httpStatus =
                                    envelope && typeof envelope === "object" && "http_status" in envelope
                                        ? envelope.http_status
                                        : undefined;
                                const res =
                                    envelope && typeof envelope === "object" && "response" in envelope
                                        ? envelope.response
                                        : envelope;
                                const isArray = Array.isArray(res);
                                const isObject = res && typeof res === "object" && !isArray;
                                const primary = isArray ? (res[res.length - 1] || {}) : (isObject ? res : {});
                                const nested = (primary && typeof primary === "object" && primary.data && typeof primary.data === "object")
                                    ? primary.data
                                    : {};

                                const findKeyLike = (obj, patterns) => {
                                    if (!obj || typeof obj !== "object") return undefined;
                                    const keys = Object.keys(obj);
                                    for (const p of patterns) {
                                        for (const key of keys) {
                                            if (p.test(key)) {
                                                const value = obj[key];
                                                if (value !== undefined && value !== null && value !== "") {
                                                    return value;
                                                }
                                            }
                                        }
                                    }
                                    return undefined;
                                };

                                const documentId =
                                    findKeyLike(primary, [/^id$/i]) ??
                                    findKeyLike(nested, [/^id$/i]) ??
                                    "-";
                                const status =
                                    findKeyLike(primary, [/status/i]) ??
                                    findKeyLike(nested, [/status/i]) ??
                                    "-";

                                const rawJson = frappe.utils.escape_html(JSON.stringify(res, null, 2));

                                const isHttpSuccess =
                                    typeof httpStatus === "number" && httpStatus >= 200 && httpStatus < 300;
                                const indicator = !isHttpSuccess
                                    ? "red"
                                    : (status === "reported" ? "green" : "orange");

                                const html = `
                                    <p><b>HTTP Status:</b> ${frappe.utils.escape_html(String(httpStatus ?? "-"))}</p>
                                    <p><b>Document ID:</b> ${frappe.utils.escape_html(String(documentId))}</p>
                                    <p><b>Status:</b> ${frappe.utils.escape_html(String(status))}</p>
                                    <p style="margin-top:12px;"><b>Response</b></p>
                                    <pre style="white-space:pre-wrap;background:#f6f8fa;padding:12px;border-radius:6px;max-height:400px;overflow:auto;font-size:12px;">${rawJson}</pre>
                                `;

                                frappe.msgprint({
                                    title: __("Document Status"),
                                    message: html,
                                    indicator: indicator,
                                    wide: true
                                });

                                frm.reload_doc();
                            }
                        }
                    });
                });
            }

            // Hide XML / PDF buttons if already attached
            const attachments = (frm.get_docinfo() && frm.get_docinfo().attachments) || [];
            const has_ext = (ext) => attachments.some(a =>
                ((a.file_name || a.file_url || "").toLowerCase()).endsWith(ext)
            );
            const has_xml = has_ext(".xml");
            const has_pdf = has_ext(".pdf");

            if (!has_xml) {
                frm.add_custom_button(__('XML'), function () {
                    frappe.call({
                        method: "uae_erpgulf.uae_erpgulf.attach.get_document_xml",
                        args: {
                            doctype: "Sales Invoice",
                            invoice_name: frm.doc.name
                        },
                        freeze: true,
                        freeze_message: __("Fetching Document XML..."),
                        callback: function (r) {
                            if (r.message && r.message.file_url) {
                                frappe.msgprint({
                                    title: __("Document XML"),
                                    message: `<p>XML fetched and attached to this invoice.</p><p><a href="${r.message.file_url}" target="_blank">${__("Open XML")}</a></p>`,
                                    indicator: "green"
                                });
                                frm.reload_doc();
                            }
                        }
                        // No custom error handling on purpose - attach.py throws
                        // the actual ASP reason, and frappe.call's default error
                        // dialog shows it.
                    });
                }, __('Get Document'));
            }

            if (!has_pdf) {
                frm.add_custom_button(__('PDF'), function () {
                    frappe.call({
                        method: "uae_erpgulf.uae_erpgulf.attach.get_document_pdf",
                        args: {
                            doctype: "Sales Invoice",
                            invoice_name: frm.doc.name
                        },
                        freeze: true,
                        freeze_message: __("Fetching Document PDF..."),
                        callback: function (r) {
                            if (r.message && r.message.file_url) {
                                frappe.msgprint({
                                    title: __("Document PDF"),
                                    message: `<p>PDF fetched and attached to this invoice.</p><p><a href="${r.message.file_url}" target="_blank">${__("Open PDF")}</a></p>`,
                                    indicator: "green"
                                });
                                frm.reload_doc();
                            }
                        }
                    });
                }, __('Get Document'));
            }
        }
    }
});

frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {
        toggle_return_against_field(frm);
    },

    company(frm) {
        toggle_return_against_field(frm);
    },

    is_return(frm) {
        toggle_return_against_field(frm);
    }
});

function toggle_return_against_field(frm) {
    if (!frm.doc.company) {
        frm.set_df_property("custom_return_against_for_zatca", "hidden", 1);
        return;
    }

    frappe.db.get_value(
        "Company",
        frm.doc.company,
        "custom_allow_creditnote_without_original_invoice_in_the_system"
    ).then((r) => {
        const show_field =
            frm.doc.is_return == 1 &&
            cint(r.message.custom_allow_creditnote_without_original_invoice_in_the_system) == 1;

        frm.set_df_property(
            "custom_return_against_for_zatca",
            "hidden",
            !show_field
        );
    });
}