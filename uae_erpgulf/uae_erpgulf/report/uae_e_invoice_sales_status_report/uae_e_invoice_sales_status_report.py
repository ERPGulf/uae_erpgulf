import frappe
from frappe import _

def execute(filters=None):
    if not filters:
        filters = {}

    columns = get_columns()
    data = get_data(filters)

    return columns, data, None, None


def get_columns():
    return [
        {
            'fieldname': 'name',
            'label': _('Inv. Number'),
            'fieldtype': 'Link',
            'options': 'Sales Invoice',
            'width': 200
        },
        {
            'fieldname': 'posting_date',
            'label': _('Date'),
            'fieldtype': 'Date',
            'width': 140
        },
        {
            'fieldname': 'customer_name',
            'label': _('Customer'),
            'fieldtype': 'Data',
            'width': 200
        },
        {
            'fieldname': 'grand_total',
            'label': _('Total'),
            'fieldtype': 'Currency',
            'width': 160
        },
        {
            'fieldname': 'custom_reporting_status',
            'label': _('Status'),
            'fieldtype': 'Data',
            'width': 160
        }
    ]


def get_data(filters):
    conditions = []
    params = {}

    # Date filter
    if filters.get("dt_from") and filters.get("dt_to"):
        conditions.append("posting_date BETWEEN %(dt_from)s AND %(dt_to)s")
        params["dt_from"] = filters.get("dt_from")
        params["dt_to"] = filters.get("dt_to")

    # Status filter (optimized)
    status = filters.get("status")

    if status == "Not Submitted":
        conditions.append("(docstatus = 0 OR IFNULL(custom_reporting_status, '') = '')")
    elif status:
        conditions.append("custom_reporting_status = %(status)s")
        params["status"] = status

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    query = f"""
        SELECT
            name,
            customer_name,
            posting_date,
            grand_total,
            custom_reporting_status
        FROM `tabSales Invoice`
        WHERE {where_clause}
        ORDER BY posting_date DESC
    """

    return frappe.db.sql(query, params, as_dict=True)