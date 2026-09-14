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
        if (!frm.doc.__islocal && frm.doc.custom_uae_einvoice_status !== "Not Submitted") {
            frm.add_custom_button(__('Get Document Status'), function () {
                frappe.call({
                    method: "uae_erpgulf.uae_erpgulf.send_purchase.get_document_status",
                    args: {
                        invoice_name: frm.doc.name
                    },
                    freeze: true,
                    freeze_message: __("Checking Document Status..."),
                    callback: function (r) {
                        if (r.message) {
                            // Same generic, envelope-aware dialog as the Sales Invoice
                            // "Get Document Status" button (public/js/sales_invoice.js) -
                            // send_purchase.get_document_status now returns the same
                            // {http_status, response} shape as verify_token.py's version,
                            // instead of the old hardcoded Flick-only {status, message,
                            // data: {...}} table, which would have shown "-" for every
                            // row (or just broken) for Marmin, and no longer matches
                            // this envelope's shape either way.
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

            // Same "Get Document" dropdown as Sales Invoice
            // (public/js/sales_invoice.js) - Marmin generates XML/PDF
            // asynchronously, so this is how you fetch either manually once
            // the ASP has actually finished (check "Get Document Status"
            // first if unsure). XML and PDF share the same group name
            // ("Get Document") so frm.add_custom_button renders them as ONE
            // dropdown with two menu items, exactly like the Sales Invoice
            // version - just with doctype: "Purchase Invoice" here.
            frm.add_custom_button(__('XML'), function () {
                frappe.call({
                    method: "uae_erpgulf.uae_erpgulf.attach.get_document_xml",
                    args: {
                        doctype: "Purchase Invoice",
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
                    // No custom error handling here on purpose - same as
                    // Sales Invoice's version: attach.py's get_document_xml
                    // throws the actual reason (e.g. not generated yet), so
                    // frappe.call's default error dialog already shows
                    // something useful.
                });
            }, __('Get Document'));

            frm.add_custom_button(__('PDF'), function () {
                frappe.call({
                    method: "uae_erpgulf.uae_erpgulf.attach.get_document_pdf",
                    args: {
                        doctype: "Purchase Invoice",
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
});



frappe.ui.form.on('Purchase Invoice', {
    refresh: function (frm) {
        frm.add_custom_button(__('Get FTA Incoming Invoices'), function () {
            get_fta_incoming_invoices(frm);
        }, __('Get Items From'));
    }
});

function get_fta_incoming_invoices(frm) {
    frappe.call({
        method: 'uae_erpgulf.uae_erpgulf.get_purchase_inv.get_fta_incoming_invoices',
        freeze: true,
        freeze_message: __('Fetching FTA Incoming Invoices...'),
        callback: function (r) {
            console.log("FTA Invoices response:", r);
            if (r.message && r.message.length > 0) {
                show_fta_invoices_dialog(frm, r.message);
            } else {
                frappe.msgprint({
                    title: __('No Records Found'),
                    message: __('No FTA Incoming Invoices with status "Not Submitted" found.'),
                    indicator: 'orange'
                });
            }
        }
    });
}

function show_fta_invoices_dialog(frm, invoices) {
    console.log("Invoices received:", invoices);

    const docname_map = {};
    invoices.forEach(inv => {
        docname_map[inv.document_id] = inv.name;
    });
    console.log("docname_map:", docname_map);

    // Build simple HTML table instead of Frappe grid
    let table_rows = '';
    invoices.forEach((inv, idx) => {
        table_rows += `
            <tr>
                <td style="text-align:center; padding:8px;">
                    <input type="checkbox" class="fta-row-check" data-idx="${idx}" 
                           data-document_id="${inv.document_id}" 
                           data-docname="${inv.name}"
                           style="width:16px; height:16px; cursor:pointer;">
                </td>
                <td style="padding:8px;">${inv.document_id || ''}</td>
                <td style="padding:8px; font-size:12px; color:#555;">${inv.incoming_invoice_file || ''}</td>
            </tr>
        `;
    });

    const table_html = `
        <div style="margin: 10px 0;">
            <p class="text-muted">${invoices.length} record(s) found with status <b>Not Submitted</b></p>
            <table class="table table-bordered" style="width:100%; border-collapse:collapse;">
                <thead style="background:#f5f5f5;">
                    <tr>
                        <th style="width:50px; text-align:center; padding:8px;">
                            <input type="checkbox" id="fta_select_all" style="width:16px; height:16px; cursor:pointer;">
                        </th>
                        <th style="padding:8px;">Document ID</th>
                        <th style="padding:8px;">Incoming Invoice File</th>
                    </tr>
                </thead>
                <tbody id="fta_invoice_tbody">
                    ${table_rows}
                </tbody>
            </table>
        </div>
        <div style="text-align:right; padding: 5px 0 10px 0;">
            <button class="btn btn-primary" id="fta_import_btn">Import Selected</button>
        </div>
    `;

    const dialog = new frappe.ui.Dialog({
        title: __('FTA Incoming Invoices - Not Submitted'),
        fields: [
            {
                fieldtype: 'HTML',
                fieldname: 'fta_table_html',
                options: table_html
            }
        ]
    });

    dialog.show();

    setTimeout(() => {
        // Select All checkbox
        const select_all = document.getElementById('fta_select_all');
        if (select_all) {
            select_all.addEventListener('change', function () {
                document.querySelectorAll('.fta-row-check').forEach(cb => {
                    cb.checked = select_all.checked;
                });
            });
        }

        // Import button
        const btn = document.getElementById('fta_import_btn');
        console.log("Import button found:", btn);

        if (btn) {
            btn.addEventListener('click', function () {
                console.log("=== IMPORT CLICKED ===");

                // Read checked checkboxes directly from DOM
                const checked_boxes = document.querySelectorAll('.fta-row-check:checked');
                console.log("Checked boxes count:", checked_boxes.length);

                if (checked_boxes.length === 0) {
                    frappe.msgprint({
                        title: __('Nothing Selected'),
                        message: __('Please select at least one invoice.'),
                        indicator: 'red'
                    });
                    return;
                }

                const selected_rows = [];
                checked_boxes.forEach(cb => {
                    const document_id = cb.getAttribute('data-document_id');
                    const docname = cb.getAttribute('data-docname');
                    console.log("Selected:", document_id, "->", docname);
                    selected_rows.push({
                        document_id: document_id,
                        docname: docname
                    });
                });

                console.log("Selected rows:", selected_rows);

                btn.disabled = true;
                btn.textContent = 'Importing...';

                process_invoices_sequentially(selected_rows, 0, [], dialog, frm);
            });
        } else {
            console.error("Import button NOT found in DOM");
        }
    }, 300);
}
function process_invoices_sequentially(rows, index, results, dialog, frm) {
    console.log(`Processing ${index + 1} of ${rows.length}`);

    if (index >= rows.length) {
        dialog.hide();

        const success = results.filter(r => r.success);
        const failed = results.filter(r => !r.success);

        console.log("Done. Success:", success.length, "Failed:", failed.length);

        let msg = `<b>${success.length} Purchase Invoice(s) created:</b><br>`;
        success.forEach(r => {
            msg += `✅ <a href="/app/purchase-invoice/${r.purchase_invoice}" 
                        target="_blank">${r.purchase_invoice}</a> 
                        &nbsp;←&nbsp; Document ID: ${r.document_id}<br>`;
        });

        if (failed.length > 0) {
            msg += `<br><b>${failed.length} Failed:</b><br>`;
            failed.forEach(r => {
                msg += `❌ Document ID: ${r.document_id} — ${r.error}<br>`;
            });
        }

        frappe.msgprint({
            title: __('Import Complete'),
            message: msg,
            indicator: success.length > 0 ? 'green' : 'red'
        });

        // ✅ Navigate into the draft PI
        if (success.length === 1) {
            // Single invoice → open it directly
            frappe.set_route('Form', 'Purchase Invoice', success[0].purchase_invoice);
        } else if (success.length > 1) {
            // Multiple invoices → open list view filtered to show only created ones
            frappe.set_route('List', 'Purchase Invoice', {
                name: ['in', success.map(r => r.purchase_invoice)]
            });
        } else {
            // All failed → just reload current doc
            frm.reload_doc();
        }

        return;
    }

    const row = rows[index];
    const docname = row.docname;

    console.log("Calling API for docname:", docname);

    if (!docname) {
        console.error("No docname for row:", row);
        results.push({
            success: false,
            document_id: row.document_id,
            error: 'Could not resolve docname'
        });
        process_invoices_sequentially(rows, index + 1, results, dialog, frm);
        return;
    }

    frappe.call({
        method: 'uae_erpgulf.uae_erpgulf.get_purchase_inv.create_purchase_invoice_from_fta',
        args: { docname: docname },
        freeze: true,
        freeze_message: __("Importing {0}...", [row.document_id]),
        callback: function (r) {
            console.log("API response for", docname, ":", r);

            if (r.message && r.message.error) {
                console.error("Server error:", r.message.message);
                results.push({
                    success: false,
                    document_id: row.document_id,
                    error: r.message.message
                });
            } else if (r.message && r.message.purchase_invoice) {
                console.log("Created PI:", r.message.purchase_invoice);
                results.push({
                    success: true,
                    purchase_invoice: r.message.purchase_invoice,
                    document_id: row.document_id
                });
            } else {
                console.error("Unexpected response:", r);
                results.push({
                    success: false,
                    document_id: row.document_id,
                    error: 'Unexpected response — check console'
                });
            }
            process_invoices_sequentially(rows, index + 1, results, dialog, frm);
        },
        error: function (err) {
            console.error("Call error:", err);
            results.push({
                success: false,
                document_id: row.document_id,
                error: err.message || 'Server error'
            });
            process_invoices_sequentially(rows, index + 1, results, dialog, frm);
        }
    });
}













frappe.ui.form.on('Purchase Invoice', {
    refresh: function (frm) {
        if (frm.doc.docstatus !== 2) {
            frm.add_custom_button(__('Match & Approve'), function () {
                match_and_approve_fta(frm);
            });

            if (frm.doc.custom_document_id) {
                check_fta_match_status(frm);
            }
        }
    }
});

function match_and_approve_fta(frm) {
    if (!frm.doc.custom_document_id) {
        frappe.msgprint({
            title: __('Missing Document ID'),
            message: __('This Purchase Invoice has no FTA Document ID to match against.'),
            indicator: 'orange'
        });
        return;
    }

    frappe.call({
        method: 'frappe.client.get_list',
        args: {
            doctype: 'UAE Incoming Invoices',
            filters: { document_id: frm.doc.custom_document_id },
            fields: ['name', 'document_id', 'status']
        },
        callback: function (r) {
            if (r.message && r.message.length > 0) {
                let fta_doc = r.message[0];

                if (fta_doc.document_id === frm.doc.custom_document_id) {
                    frm.dashboard.set_headline(
                        '<span class="indicator green">✅ Matched & Approved by FTA — Document ID: ' + frm.doc.custom_document_id + '</span>'
                    );

                    frappe.show_alert({
                        message: __('✅ Matched! Purchase Invoice is approved by FTA. FTA Record: ' + fta_doc.name),
                        indicator: 'green'
                    }, 8);

                    if (frm.fields_dict['custom_fta_match_status']) {
                        frappe.call({
                            method: 'frappe.client.set_value',
                            args: {
                                doctype: 'Purchase Invoice',
                                name: frm.doc.name,
                                fieldname: 'custom_fta_match_status',
                                value: 'Matched & Approved'
                            },
                            callback: function () {
                                frm.reload_doc();
                            }
                        });
                    }

                } else {
                    frappe.show_alert({
                        message: __('❌ Document ID does not match any FTA record.'),
                        indicator: 'red'
                    }, 8);
                }

            } else {
                frappe.msgprint({
                    title: __('No FTA Match Found'),
                    message: __('No UAE Incoming Invoice found with Document ID: <b>' + frm.doc.custom_document_id + '</b>'),
                    indicator: 'red'
                });
            }
        }
    });
}

function check_fta_match_status(frm) {
    frappe.call({
        method: 'frappe.client.get_list',
        args: {
            doctype: 'UAE Incoming Invoices',
            filters: { document_id: frm.doc.custom_document_id },
            fields: ['name', 'document_id', 'status']
        },
        callback: function (r) {
            if (r.message && r.message.length > 0) {
                let fta_doc = r.message[0];
                if (fta_doc.document_id === frm.doc.custom_document_id) {
                    frm.dashboard.set_headline(
                        '<span class="indicator green">✅ Matched & Approved by FTA — Document ID: ' + frm.doc.custom_document_id + '</span>'
                    );
                }
            }
        }
    });
}