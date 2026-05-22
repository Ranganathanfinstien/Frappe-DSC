"""
Data Retention — daily scheduled task.

Purges old DSC Signing Requests beyond the configured retention period.
Audit Events are NEVER deleted (legal requirement).
"""

import frappe
from frappe.utils import add_years, now_datetime


def purge_old_requests():
	"""Daily job: delete signing requests older than retention_years_for_requests.

	Only deletes requests in terminal states (Signed, Failed, Cancelled).
	Audit Events are never deleted.
	"""
	settings = frappe.get_single("DSC Settings")
	retention_years = settings.retention_years_for_requests or 7

	cutoff_date = add_years(now_datetime(), -retention_years)

	old_requests = frappe.get_all(
		"DSC Signing Request",
		filters={
			"status": ["in", ["Signed", "Failed", "Cancelled"]],
			"created_on": ["<", cutoff_date],
		},
		fields=["name"],
	)

	for req in old_requests:
		frappe.delete_doc("DSC Signing Request", req.name, force=True)

	if old_requests:
		# scheduled retention job: explicit
		# commit so the purge is durable even if a downstream log step raises.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		frappe.logger().info(f"DSC Retention: purged {len(old_requests)} old signing requests")
