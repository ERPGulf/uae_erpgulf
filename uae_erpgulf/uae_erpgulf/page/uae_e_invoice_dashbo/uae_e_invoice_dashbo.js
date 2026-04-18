frappe.pages['uae-e-invoice-dashbo'].on_page_load = function (wrapper) {

	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'UAE E-Invoice Dashboard',
		single_column: true
	});

	const body = $(page.body);

	// ✅ SECTIONS
	body.append(`<div id="dashboard-cards"></div>`);
	body.append(`<div id="reporting-chart" style="margin-top:40px;"></div>`);
	body.append(`<div id="sales-invoice-list" style="margin-top:40px;"></div>`);
	body.append(`<div id="purchase-invoice-list" style="margin-top:40px;"></div>`);

	// ✅ CALL FUNCTIONS
	render_cards();
	render_reporting_chart();
	render_sales_invoice_list();
	render_purchase_invoice_list();
};



// ======================
// ✅ COMMON COUNT
// ======================
function get_count(doctype, filters) {
	return frappe.call({
		method: "frappe.client.get_count",
		args: { doctype, filters }
	}).then(r => r.message || 0);
}



// ======================
// ✅ CARDS
// ======================
function render_cards() {

	const container = $('#dashboard-cards');
	container.empty();

	const doctypes = ["Sales Invoice", "Purchase Invoice"];

	const sections = [
		{ title: "Reported", field: "custom_reporting_status", value: "reported", color: "#28a745" },
		{ title: "Success", field: "custom_uae_einvoice_status", value: "Success", color: "#17a2b8" },
		{ title: "Failed", field: "custom_reporting_status", value: "failed", color: "#dc3545" },
		{ title: "Not Submitted", field: "custom_uae_einvoice_status", value: "Not Submitted", color: "#ffc107" },
		{ title: "Cancelled", field: "docstatus", value: 2, color: "#6c757d" }
	];

	for (let i = 0; i < sections.length; i += 3) {

		let row_div = $(`<div class="row" style="margin-bottom:30px;"></div>`);

		sections.slice(i, i + 3).forEach(section => {

			let section_div = $(`
				<div class="col-lg-4">
					<h4 style="margin-bottom:15px;">${section.title}</h4>
					<div class="row inner-row"></div>
				</div>
			`);

			const inner_row = section_div.find('.inner-row');

			Promise.all(doctypes.map(dt => {

				let filters = {};

				if (section.field === "docstatus") {
					filters.docstatus = 2;
				} else {
					filters[section.field] = section.value;
				}

				return get_count(dt, filters);

			})).then(([sales_count, purchase_count]) => {

				const cards = [
					{ label: "Sales Invoice", value: sales_count },
					{ label: "Purchase Invoice", value: purchase_count }
				];

				cards.forEach(card => {

					const reportName = card.label === "Sales Invoice"
						? "UAE E-Invoice Sales Status Report"
						: "UAE E-Invoice Purchase Status Report";

					const url = `/app/query-report/${encodeURIComponent(reportName)}?status=${encodeURIComponent(section.title)}`;

					inner_row.append(`
						<div class="col-md-6">
							<a href="${url}" style="text-decoration:none; color:inherit;">
								<div style="
									background:#fff;
									padding:18px;
									border-radius:10px;
									box-shadow:0 2px 6px rgba(0,0,0,0.1);
									text-align:center;
									margin-bottom:12px;
								">
									<h5>${card.label}</h5>
									<p>${section.title}</p>
									<h2 style="color:${section.color};">${card.value}</h2>
								</div>
							</a>
						</div>
					`);
				});

			});

			row_div.append(section_div);
		});

		container.append(row_div);
	}
}



// ======================
// ✅ CHART
// ======================
function render_reporting_chart() {

	Promise.all([
		get_count("Sales Invoice", { custom_reporting_status: "reported" }),
		get_count("Sales Invoice", { custom_reporting_status: "failed" }),
		get_count("Purchase Invoice", { custom_reporting_status: "reported" }),
		get_count("Purchase Invoice", { custom_reporting_status: "failed" })
	]).then(([s_reported, s_failed, p_reported, p_failed]) => {

		new frappe.Chart("#reporting-chart", {
			title: "Reporting Status",
			data: {
				labels: ["Reported", "Failed"],
				datasets: [
					{ name: "Sales", values: [s_reported, s_failed] },
					{ name: "Purchase", values: [p_reported, p_failed] }
				]
			},
			type: 'bar',
			height: 300
		});

	});
}



// ======================
// ✅ SALES LIST
// ======================
function render_sales_invoice_list() {

	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Sales Invoice",
			fields: [
				"name",
				"customer",
				"posting_date",
				"custom_reporting_status",
				"custom_uae_einvoice_status",
				"grand_total"
			],
			limit_page_length: 20,
			order_by: "posting_date desc"
		},
		callback: function (r) {

			if (r.message) {

				let rows = r.message.map(row => `
					<tr>
						<td>${row.name}</td>
						<td>${row.customer}</td>
						<td>${row.posting_date}</td>
						<td>${row.custom_reporting_status || '-'}</td>
						<td>${row.custom_uae_einvoice_status || 'Not Submitted'}</td>
						<td>${row.grand_total}</td>
					</tr>
				`).join("");

				let html = `
					<h4>Sales Invoice List</h4>
					<table class="table table-bordered">
						<thead>
							<tr>
								<th>Invoice</th>
								<th>Customer</th>
								<th>Date</th>
								<th>Reporting</th>
								<th>UAE Status</th>
								<th>Total</th>
							</tr>
						</thead>
						<tbody>${rows}</tbody>
					</table>
				`;

				$("#sales-invoice-list").html(html);
			}
		}
	});
}



// ======================
// ✅ PURCHASE LIST
// ======================
function render_purchase_invoice_list() {

	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Purchase Invoice",
			fields: [
				"name",
				"supplier",
				"posting_date",
				"custom_reporting_status",
				"custom_uae_einvoice_status",
				"grand_total"
			],
			limit_page_length: 20,
			order_by: "posting_date desc"
		},
		callback: function (r) {

			if (r.message) {

				let rows = r.message.map(row => `
					<tr>
						<td>${row.name}</td>
						<td>${row.supplier}</td>
						<td>${row.posting_date}</td>
						<td>${row.custom_reporting_status || '-'}</td>
						<td>${row.custom_uae_einvoice_status || 'Not Submitted'}</td>
						<td>${row.grand_total}</td>
					</tr>
				`).join("");

				let html = `
					<h4>Purchase Invoice List</h4>
					<table class="table table-bordered">
						<thead>
							<tr>
								<th>Invoice</th>
								<th>Supplier</th>
								<th>Date</th>
								<th>Reporting</th>
								<th>UAE Status</th>
								<th>Total</th>
							</tr>
						</thead>
						<tbody>${rows}</tbody>
					</table>
				`;

				$("#purchase-invoice-list").html(html);
			}
		}
	});
}