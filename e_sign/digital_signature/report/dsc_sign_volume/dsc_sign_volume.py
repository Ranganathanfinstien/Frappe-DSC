"""
DSC Sign Volume — count of signing requests grouped by day, profile, and source DocType.

PRD §F9.3.
"""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})

	columns = [
		{"label": _("Date"), "fieldname": "day", "fieldtype": "Date", "width": 110},
		{"label": _("Source DocType"), "fieldname": "source_doctype", "fieldtype": "Data", "width": 160},
		{"label": _("Profile"), "fieldname": "profile", "fieldtype": "Link", "options": "DSC Profile", "width": 200},
		{"label": _("Total"), "fieldname": "total", "fieldtype": "Int", "width": 90},
		{"label": _("Signed"), "fieldname": "signed", "fieldtype": "Int", "width": 90},
		{"label": _("Pending"), "fieldname": "pending", "fieldtype": "Int", "width": 90},
		{"label": _("Failed"), "fieldname": "failed", "fieldtype": "Int", "width": 90},
		{"label": _("Cancelled"), "fieldname": "cancelled", "fieldtype": "Int", "width": 100},
	]

	conditions = []
	params = {}
	if filters.get("from_date"):
		conditions.append("DATE(creation) >= %(from_date)s")
		params["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		conditions.append("DATE(creation) <= %(to_date)s")
		params["to_date"] = filters["to_date"]
	if filters.get("profile"):
		conditions.append("profile = %(profile)s")
		params["profile"] = filters["profile"]
	if filters.get("source_doctype"):
		conditions.append("source_doctype = %(source_doctype)s")
		params["source_doctype"] = filters["source_doctype"]

	where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

	query = (
		"SELECT "
		"DATE(creation) AS day, "
		"source_doctype, "
		"profile, "
		"COUNT(*) AS total, "
		"SUM(CASE WHEN status = 'Signed' THEN 1 ELSE 0 END) AS signed, "
		"SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END) AS pending, "
		"SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) AS failed, "
		"SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled "
		"FROM `tabDSC Signing Request` "
		+ where_clause
		+ " GROUP BY day, source_doctype, profile "
		"ORDER BY day DESC"
	)

	rows = frappe.db.sql(query, params, as_dict=True)

	chart = {
		"data": {
			"labels": [str(r.day) for r in rows[:30]][::-1],
			"datasets": [{"name": "Signed", "values": [r.signed or 0 for r in rows[:30]][::-1]}],
		},
		"type": "bar",
	}

	return columns, rows, None, chart
