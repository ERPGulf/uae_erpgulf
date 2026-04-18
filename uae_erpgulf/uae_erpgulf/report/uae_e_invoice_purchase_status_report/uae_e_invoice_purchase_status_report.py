import frappe
from frappe import _


def execute(filters=None):
    if not filters:
        filters = {}

    columns = get_columns()
    data = get_data(filters)

    return columns, data, None, None


# ======================
# ✅ COLUMNS
# ======================
def get_columns():
    return [
        {
            'fieldname': 'name',
            'label': _('Inv. Number'),
            'fieldtype': 'Link',
            'options': 'Purchase Invoice',
            'width': 200
        },
        {
            'fieldname': 'posting_date',
            'label': _('Date'),
            'fieldtype': 'Date',
            'width': 140
        },
        {
            'fieldname': 'supplier',
            'label': _('Supplier'),
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
            'label': _('Reporting Status'),
            'fieldtype': 'Data',
            'width': 160
        },
        {
            'fieldname': 'custom_uae_einvoice_status',
            'label': _('UAE Status'),
            'fieldtype': 'Data',
            'width': 180
        }
    ]


# ======================
# ✅ DATA
# ======================
def get_data(filters):
    conditions = []
    params = {}

    # ✅ Date filter
    if filters.get("dt_from") and filters.get("dt_to"):
        conditions.append("posting_date BETWEEN %(dt_from)s AND %(dt_to)s")
        params["dt_from"] = filters.get("dt_from")
        params["dt_to"] = filters.get("dt_to")

    status = filters.get("status")

    # ======================
    # ✅ STATUS LOGIC
    # ======================
    if status == "Reported":
        conditions.append("custom_reporting_status = 'reported'")

    elif status == "Failed":
        conditions.append("custom_reporting_status = 'failed'")

    elif status == "Success":
        conditions.append("custom_uae_einvoice_status = 'Success'")

    elif status == "Not Submitted":
        conditions.append("""
            (
                docstatus = 0
                OR IFNULL(custom_uae_einvoice_status, '') = ''
                OR custom_uae_einvoice_status = 'Not Submitted'
            )
        """)

    elif status == "Cancelled":
        conditions.append("docstatus = 2")

    # ✅ fallback
    elif status:
        conditions.append("""
            (
                custom_reporting_status = %(status)s
                OR custom_uae_einvoice_status = %(status)s
            )
        """)
        params["status"] = status

    # ======================
    # ✅ FINAL QUERY
    # ======================
    where_clause = " AND ".join(conditions) if conditions else "1=1"

    query = f"""
        SELECT
            name,
            supplier,
            posting_date,
            grand_total,
            custom_reporting_status,
            custom_uae_einvoice_status,
            docstatus
        FROM `tabPurchase Invoice`
        WHERE {where_clause}
        ORDER BY posting_date DESC
    """

    return frappe.db.sql(query, params, as_dict=True)