"""
Cleanup — hourly scheduled task.

Expires stale signing requests that have been In Progress too long
(beyond the signing_timeout_seconds configured in DSC Settings).
"""

import frappe
from frappe.utils import add_to_date, now_datetime


def expire_stale_pending_requests():
	"""Hourly job: find In Progress requests that exceeded the signing timeout
	and reset them back to Pending so the signer can retry."""
	settings = frappe.get_single("DSC Settings")
	timeout_seconds = settings.signing_timeout_seconds or 180

	cutoff = add_to_date(now_datetime(), seconds=-timeout_seconds)

	stale_requests = frappe.get_all(
		"DSC Signing Request",
		filters={
			"status": "In Progress",
			"modified": ["<", cutoff],
		},
		fields=["name"],
	)

	for req in stale_requests:
		frappe.db.set_value(
			"DSC Signing Request", req.name,
			{
				"status": "Failed",
				"failure_reason": f"Signing timed out after {timeout_seconds} seconds",
			},
		)

	if stale_requests:
		# nosemgrep: frappe-manual-commit -- scheduled job: explicit commit so
		# the timeout-expiry write is durable even if a later log/notification
		# step raises.
		frappe.db.commit()
		frappe.logger().info(f"DSC Cleanup: expired {len(stale_requests)} stale signing requests")
