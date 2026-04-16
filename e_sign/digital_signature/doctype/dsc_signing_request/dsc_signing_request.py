import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class DSCSigningRequest(Document):
	def before_insert(self):
		self.created_on = now_datetime()

	def validate(self):
		self.validate_status_transition()

	def validate_status_transition(self):
		if self.is_new():
			return

		old_status = self.db_get("status")
		if old_status == self.status:
			return

		valid_transitions = {
			"Pending": ["In Progress", "Cancelled"],
			"In Progress": ["Signed", "Failed"],
			"Failed": ["Pending"],
			"Signed": [],
			"Cancelled": [],
		}

		allowed = valid_transitions.get(old_status, [])
		if self.status not in allowed:
			frappe.throw(
				f"Cannot change status from {old_status} to {self.status}. "
				f"Allowed transitions: {', '.join(allowed) or 'None (terminal state)'}"
			)

	def on_update(self):
		if self.has_value_changed("status"):
			if self.status == "Signed":
				self.db_set("signed_on", now_datetime(), update_modified=False)
			elif self.status == "Cancelled":
				self.db_set("cancelled_on", now_datetime(), update_modified=False)
