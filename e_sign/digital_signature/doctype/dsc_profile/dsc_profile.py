import frappe
from frappe.model.document import Document


class DSCProfile(Document):
	def validate(self):
		self.validate_unique_users()

	def validate_unique_users(self):
		users = [row.user for row in self.allowed_users]
		if len(users) != len(set(users)):
			frappe.throw("Each user can only be added once to the allowed users list.")
