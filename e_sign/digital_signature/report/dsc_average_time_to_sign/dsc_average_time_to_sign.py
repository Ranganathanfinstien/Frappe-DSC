"""
DSC Average Time to Sign — average sign_duration_seconds across signed requests,
grouped by profile and source DocType. PRD §F9.4.
"""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})

	columns = [
		{"label": _("Profile"), "fieldname": "profile", "fieldtype": "Link", "options": "DSC Profile", "width": 200},
		{"label": _("Source DocType"), "fieldname": "source_doctype", "fieldtype": "Data", "width": 160},
		{"label": _("Signed Count"), "fieldname": "signed_count", "fieldtype": "Int", "width": 110},
		{"label": _("Avg Time (s)"), "fieldname": "avg_seconds", "fieldtype": "Float", "precision": 1, "width": 130},
		{"label": _("Min Time (s)"), "fieldname": "min_seconds", "fieldtype": "Int", "width": 120},
		{"label": _("Max Time (s)"), "fieldname": "max_seconds", "fieldtype": "Int", "width": 120},
	]

	conditions = ["status = 'Signed'", "sign_duration_seconds IS NOT NULL"]
	params = {}
	if filters.get("from_date"):
		conditions.append("DATE(signed_on) >= %(from_date)s")
		params["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		conditions.append("DATE(signed_on) <= %(to_date)s")
		params["to_date"] = filters["to_date"]
	if filters.get("profile"):
		conditions.append("profile = %(profile)s")
		params["profile"] = filters["profile"]

	where = "WHERE " + " AND ".join(conditions)

	rows = frappe.db.sql(
		f"""
		SELECT
			profile,
			source_doctype,
			COUNT(*) AS signed_count,
			AVG(sign_duration_seconds) AS avg_seconds,
			MIN(sign_duration_seconds) AS min_seconds,
			MAX(sign_duration_seconds) AS max_seconds
		FROM `tabDSC Signing Request`
		{where}
		GROUP BY profile, source_doctype
		ORDER BY avg_seconds DESC
		""",
		params,
		as_dict=True,
	)

	return columns, rows
