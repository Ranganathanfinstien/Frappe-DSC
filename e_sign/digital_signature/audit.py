"""
Audit Logger — creates immutable DSC Audit Event records.

Every state change on a DSC Signing Request emits an audit event.
Events are append-only: no update, no delete.
"""

import json

import frappe
from frappe.utils import now_datetime


def log_event(signing_request, event_type, details=None):
	"""Create an immutable DSC Audit Event.

	Args:
		signing_request: name of the DSC Signing Request
		event_type: one of: Request Created, Rule Evaluated, Template Selected,
			Hash Computed, Agent Called, Cert Presented, Signature Returned,
			PDF Verified, Request Signed, Request Failed, Request Cancelled
		details: optional dict with additional context
	"""
	event = frappe.get_doc(
		{
			"doctype": "DSC Audit Event",
			"request": signing_request,
			"event_type": event_type,
			"occurred_at": now_datetime(),
			"actor_user": frappe.session.user,
			"client_ip": getattr(frappe.local, "request_ip", None),
			"user_agent": (
				frappe.local.request.headers.get("User-Agent", "")
				if getattr(frappe.local, "request", None)
				else None
			),
			"details_json": json.dumps(details, default=str) if details else None,
		}
	)
	event.insert(ignore_permissions=True)
	return event.name
