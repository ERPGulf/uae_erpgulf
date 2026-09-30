// Shows "Marmin Profile ID" on Customer and Supplier only when Marmin is the
// Accredited Service Provider on at least one Company. Hidden for other ASPs.
function uae_toggle_marmin_profile_id(frm) {
    frappe.call({
        method: "uae_erpgulf.uae_erpgulf.providers.marmin.adapter.is_marmin_active",
        callback: function (r) {
            frm.toggle_display("custom_marmin_profile_id", !!r.message);
        },
    });
}



frappe.ui.form.on("Supplier", {
    refresh: uae_toggle_marmin_profile_id,
});
