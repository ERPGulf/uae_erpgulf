// FTA status corner ribbon, drawn into the HTML field
// custom_uae_einvoice_status_notification. A CSS ribbon instead of the old
// PNGs: identical size and position for every status, right-aligned in its
// own column and clipped to a fixed box so it never overlaps the sidebar.
frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {
        uae_erpgulf_render_status_ribbon(frm);
    },
});

function uae_erpgulf_render_status_ribbon(frm) {
    const field = "custom_uae_einvoice_status_notification";
    const einvoice = (frm.doc.custom_uae_einvoice_status || "").toUpperCase();
    const reporting = (frm.doc.custom_reporting_status || "").toUpperCase();

    // label, ribbon colour
    let ribbon = null;
    if (einvoice === "FAILED" || reporting === "FAILED" || reporting === "REJECTED") {
        ribbon = [reporting === "REJECTED" ? "FTA Rejected" : "FTA Failed", "#E0232E"];
    } else if (einvoice === "SUCCESS" && reporting === "REPORTED") {
        ribbon = ["FTA Reported", "#23B33A"];
    } else if (einvoice === "SUCCESS" && reporting === "PENDING") {
        ribbon = ["FTA Pending", "#F29D1C"];
    } else if (einvoice === "SUCCESS" && reporting === "NOT REPORTED") {
        ribbon = ["Not Reported", "#8A8F94"];
    } else if (einvoice === "SUCCESS") {
        ribbon = ["Sent to ASP", "#2F6FD6"];
    }

    let html = " ";
    if (ribbon) {
        const [label, color] = ribbon;
        html =
            '<div style="display:flex;justify-content:flex-end">' +
            '<div style="position:relative;width:150px;height:150px;overflow:hidden;pointer-events:none">' +
            // the band
            '<div style="position:absolute;top:34px;right:-52px;width:230px;transform:rotate(45deg);' +
            "background:" + color + ";color:#ffffff;font-weight:700;font-size:15px;letter-spacing:0.3px;" +
            'text-align:center;line-height:34px;box-shadow:0 2px 4px rgba(0,0,0,0.25);">' +
            frappe.utils.escape_html(label) +
            "</div>" +
            "</div></div>";
    }
    frm.set_df_property(field, "options", html);
    frm.refresh_field(field);
}