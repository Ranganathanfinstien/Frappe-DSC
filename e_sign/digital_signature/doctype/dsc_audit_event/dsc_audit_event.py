import hashlib
import json

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class DSCAuditEvent(Document):
	def before_insert(self):
		if not self.occurred_at:
			self.occurred_at = now_datetime()
		if not self.actor_user:
			self.actor_user = frappe.session.user
		if not self.client_ip:
			self.client_ip = getattr(frappe.local, "request_ip", None)

		self.compute_event_hash()

	def compute_event_hash(self):
		hash_input = json.dumps(
			{
				"request": self.request,
				"event_type": self.event_type,
				"occurred_at": str(self.occurred_at),
				"actor_user": self.actor_user,
				"details_json": self.details_json or "",
			},
			sort_keys=True,
		)
		self.event_hash = hashlib.sha256(hash_input.encode()).hexdigest()

	def on_trash(self):
		frappe.throw("DSC Audit Events cannot be deleted. They are append-only for legal compliance.")

	def before_save(self):
		if not self.is_new():
			frappe.throw("DSC Audit Events cannot be modified after creation. They are append-only.")
