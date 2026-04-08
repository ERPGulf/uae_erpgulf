// Copyright (c) 2026, erpgulf.com and contributors
// For license information, please see license.txt

frappe.query_reports["UAE E-Invoice Sales Status Report"] = {
	"filters": [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1
		},
		{
			fieldname: "dt_from",
			label: __("From"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -12),
		},
		{
			fieldname: "dt_to",
			label: __("To"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nreported\nfailed\nNot Submitted\n",
			default: "Valid"
		}
	],

	// Optional: Add event listeners or custom handlers here
	onload: function (report) {
		console.log("UAE E-Invoice Sales Status Report Loaded");
	}
};