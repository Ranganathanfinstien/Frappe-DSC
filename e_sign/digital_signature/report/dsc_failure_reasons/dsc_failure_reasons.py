"""
DSC Failure Reasons — group counts by failure_reason for triage. PRD §F9.5.
"""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})

	columns = [
		{"label": _("Failure Reason"), "fieldname": "failure_reason", "fieldtype": "Data", "width": 380},
		{"label": _("Count"), "fieldname": "count", "fieldtype": "Int", "width": 100},
		{"label": _("Latest"), "fieldname": "latest", "fieldtype": "Datetime", "width": 180},
		{"label": _("Source DocType"), "fieldname": "source_doctype", "fieldtype": "Data", "width": 160},
	]

	conditions = ["status = 'Failed'"]
	params = {}
	if filters.get("from_date"):
		conditions.append("DATE(creation) >= %(from_date)s")
		params["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		conditions.append("DATE(creation) <= %(to_date)s")
		params["to_date"] = filters["to_date"]
	if filters.get("source_doctype"):
		conditions.append("source_doctype = %(source_doctype)s")
		params["source_doctype"] = filters["source_doctype"]

	where = "WHERE " + " AND ".join(conditions)

	rows = frappe.db.sql(
		f"""
		SELECT
			COALESCE(NULLIF(TRIM(failure_reason), ''), '(no reason recorded)') AS failure_reason,
			source_doctype,
			COUNT(*) AS count,
			MAX(modified) AS latest
		FROM `tabDSC Signing Request`
		{where}
		GROUP BY failure_reason, source_doctype
		ORDER BY count DESC, latest DESC
		""",
		params,
		as_dict=True,
	)

	chart = {
		"data": {
			"labels": [(r.failure_reason or "")[:60] for r in rows[:8]],
			"datasets": [{"name": "Failures", "values": [r.count for r in rows[:8]]}],
		},
		"type": "bar",
	}

	return columns, rows, None, chart
