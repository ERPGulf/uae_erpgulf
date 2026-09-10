
// frappe.ui.form.on("Sales Invoice", {
//     refresh(frm) {

//         frm.clear_custom_buttons();

//         // Show button only if:
//         // 1. Invoice is Submitted (docstatus = 1)
//         // 2. UAE status is "Not Submitted"

//         // if (
//         //     frm.doc.docstatus === 1 &&
//         //     frm.doc.custom_uae_einvoice_status === "Not Submitted"
//         // ) {
//         if (
//             frm.doc.docstatus === 1 &&
//             (
//                 frm.doc.custom_uae_einvoice_status === "Not Submitted" ||
//                 frm.doc.custom_reporting_status === "failed"
//             )
//         ) {

//             frm.add_custom_button(
//                 __("Send Invoice"),
//                 () => {

//                     frm.call({
//                         method: "uae_erpgulf.uae_erpgulf.test.generate_and_send_einvoice",
//                         args: {
//                             doc: frm.doc   // 🔥 IMPORTANT
//                         },
//                         freeze: true,
//                         freeze_message: __("Generating and sending UAE E-Invoice..."),
//                         callback(r) {
//                             if (!r.exc) {
//                                 frappe.msgprint(__("UAE E-Invoice processed successfully"));
//                                 frm.reload_doc();
//                             }
//                         }
//                     });

//                 },
//                 __("UAE E-Invoice")
//             );
//         }
//     }
// });
// frappe.ui.form.on("Sales Invoice", {
//     refresh: function (frm) {
//         if (!frm.doc.__islocal && frm.doc.custom_uae_einvoice_status !== "Not Submitted") {
//             frm.add_custom_button(__('Get Document Status'), function () {
//                 frappe.call({
//                     method: "uae_erpgulf.uae_erpgulf.verify_token.get_document_status",
//                     args: {
//                         invoice_name: frm.doc.name
//                     },
//                     freeze: true,
//                     freeze_message: __("Checking Flick Document Status..."),
//                     callback: function (r) {
//                         if (r.message) {
//                             const res = r.message;
//                             const data = res.data || {};

//                             const rows = [
//                                 ["Status", res.status || "-"],
//                                 ["Message", res.message || "-"],
//                                 ["Document ID", data.id || "-"],
//                                 ["Exchange Status", data.exchange_status || "-"],
//                                 ["Reporting Status", data.reporting_status || "-"],
//                                 ["Reporting Reference", data.reporting_reference || "-"],
//                             ];

//                             const tableRows = rows.map(([field, value]) => `
//                                 <tr>
//                                     <td style="padding:8px 12px;border:1px solid #d1d8dd !important;font-weight:600;width:40%;">${field}</td>
//                                     <td style="padding:8px 12px;border:1px solid #d1d8dd !important;">${value}</td>
//                                 </tr>
//                             `).join("");

//                             const html = `
//                                 <style>
//                                     .flick-table { border-collapse: collapse; width: 100%; font-size: 13px; }
//                                     .flick-table th { background-color: #f0f4f7; padding: 8px 12px; border: 1px solid #d1d8dd !important; text-align: left; }
//                                     .flick-table td { border: 1px solid #d1d8dd !important; }
//                                     .flick-table tr:nth-child(even) { background-color: #f9f9f9; }
//                                 </style>
//                                 <table class="flick-table">
//                                     <thead>
//                                         <tr>
//                                             <th>Field</th>
//                                             <th>Value</th>
//                                         </tr>
//                                     </thead>
//                                     <tbody>${tableRows}</tbody>
//                                 </table>
//                             `;

//                             frappe.msgprint({
//                                 title: __("Flick Document Status"),
//                                 message: html,
//                                 indicator: data.reporting_status === "reported" ? "green" : "orange",
//                                 wide: true
//                             });

//                             frm.reload_doc();
//                         }
//                     }
//                 });
//             });
//         }
//     }
// });


// frappe.ui.form.on("Sales Invoice", {
//     refresh(frm) {
//         toggle_return_against_field(frm);
//     },

//     company(frm) {
//         toggle_return_against_field(frm);
//     },

//     is_return(frm) {
//         toggle_return_against_field(frm);
//     }
// });

// function toggle_return_against_field(frm) {
//     if (!frm.doc.company) {
//         frm.set_df_property("custom_return_against_for_zatca", "hidden", 1);
//         return;
//     }

//     frappe.db.get_value(
//         "Company",
//         frm.doc.company,
//         "custom_allow_creditnote_without_original_invoice_in_the_system"
//     ).then((r) => {
//         const show_field =
//             frm.doc.is_return == 1 &&
//             cint(r.message.custom_allow_creditnote_without_original_invoice_in_the_system) == 1;

//         frm.set_df_property(
//             "custom_return_against_for_zatca",
//             "hidden",
//             !show_field
//         );
//     });
// }


frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {

        frm.clear_custom_buttons();

        // Show button only if:
        // 1. Invoice is Submitted (docstatus = 1)
        // 2. UAE status is "Not Submitted"

        // if (
        //     frm.doc.docstatus === 1 &&
        //     frm.doc.custom_uae_einvoice_status === "Not Submitted"
        // ) {
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
frappe.ui.form.on("Sales Invoice", {
    refresh: function (frm) {
        if (!frm.doc.__islocal && frm.doc.custom_uae_einvoice_status !== "Not Submitted") {
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
                            const res = r.message;

                            // No fixed table of named fields anymore - different ASPs shape
                            // this response too differently for that (Flick nests under
                            // "data"; Marmin's peppol-status-logs has no confirmed shape at
                            // all yet, and may well be a list of log entries rather than one
                            // object). Just show the raw response always, and opportunistically
                            // pull out a document id (any key that looks like "id"/"uuid") and a
                            // single status line (any key that looks like "status") if either
                            // is actually present - checked on the response itself, one level
                            // of "data" nesting under it, and (if the response is a list) its
                            // last entry, since that covers every shape seen so far without
                            // hardcoding one ASP's field names.
                            const isArray = Array.isArray(res);
                            const isObject = res && typeof res === "object" && !isArray;
                            const primary = isArray ? (res[res.length - 1] || {}) : (isObject ? res : {});
                            const nested = (primary && typeof primary === "object" && primary.data && typeof primary.data === "object")
                                ? primary.data
                                : {};

                            // Loops patterns in the OUTER loop, keys in the inner one - so the
                            // pattern list order is a real priority order, not just "whichever
                            // key happens to come first in the object". That distinction
                            // matters here: Marmin can have BOTH an "id" and a "document_id" key
                            // on the same response, and Marmin's own convention (confirmed
                            // against marmin/adapter.py's get_document_xml/get_document_status,
                            // which always read response_data["id"]) is that "id" - never
                            // "document_id" - is the real one. The previous version checked
                            // patterns.some(...) per key in object key order, so a "document_id"
                            // key appearing before "id" in the response would have won by
                            // accident.
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

                            // Both ASPs' own adapters agree on this: Marmin's
                            // get_document_xml/get_document_status (marmin/adapter.py) read
                            // response_data["id"], and Flick's get_document_status/get_document_xml
                            // (flick/adapter.py) read response_data["data"]["id"] - same plain
                            // "id" field either way, just nested one level differently. Neither
                            // ASP actually has a "document_id" or "uuid" field, so just look for
                            // "id" - on the response itself and one level under "data" - instead
                            // of guessing at names nothing really sends.
                            const documentId =
                                findKeyLike(primary, [/^id$/i]) ??
                                findKeyLike(nested, [/^id$/i]) ??
                                "-";
                            const status =
                                findKeyLike(primary, [/status/i]) ??
                                findKeyLike(nested, [/status/i]) ??
                                "-";

                            const rawJson = frappe.utils.escape_html(JSON.stringify(res, null, 2));

                            const html = `
                                <p><b>Document ID:</b> ${frappe.utils.escape_html(String(documentId))}</p>
                                <p><b>Status:</b> ${frappe.utils.escape_html(String(status))}</p>
                                <p style="margin-top:12px;"><b>Response</b></p>
                                <pre style="white-space:pre-wrap;background:#f6f8fa;padding:12px;border-radius:6px;max-height:400px;overflow:auto;font-size:12px;">${rawJson}</pre>
                            `;

                            frappe.msgprint({
                                title: __("Document Status"),
                                message: html,
                                indicator: status === "reported" ? "green" : "orange",
                                wide: true
                            });

                            frm.reload_doc();
                        }
                    }
                });
            });

            // Marmin generates XML asynchronously (a "not generated yet"
            // response right after submit is normal, not a bug - see
            // AUTO_FETCH_DOCUMENTS_ON_SUBMIT in providers/base.py), so
            // unlike Flick, nothing fetches it automatically at submit time
            // for Marmin. This button is how you fetch it manually once
            // Marmin has actually finished - check "Get Document Status"
            // first if you're not sure whether it's ready yet.
            frm.add_custom_button(__('Get Document XML'), function () {
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
                    // No custom error handling here on purpose - if the ASP
                    // hasn't generated the XML yet (Marmin) or doesn't
                    // support XML at all, attach.py's get_document_xml now
                    // throws the ACTUAL reason (e.g. "Marmin API Error: XML
                    // not generated for document ...") instead of a fixed
                    // generic message, so frappe.call's default error
                    // dialog already shows something useful.
                });
            });
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