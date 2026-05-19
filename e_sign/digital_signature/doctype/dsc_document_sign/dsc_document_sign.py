# Copyright (c) 2026, Ragav and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class DSCDocumentSign(Document):
	"""Ad-hoc document signing.

	Upload an arbitrary PDF, place the signature box interactively, and sign
	it with a DSC token through the same deferred-signing pipeline used for
	rule-based document signing.

	Saving a record that has a PDF, a profile and a placed signature box
	auto-creates a Pending DSC Signing Request. The global "Sign with DSC"
	button (e_sign.js) then drives the browser ↔ agent ↔ server handshake;
	api/signing.py recognises this doctype and feeds the uploaded PDF plus the
	chosen placement into the signing engine instead of a print format.
	"""

	def validate(self):
		if not self.status:
			self.status = "Draft"

		# Surface an inactive/expired profile early rather than at sign time.
		if self.profile:
			profile = frappe.db.get_value(
				"DSC Profile", self.profile, ["is_active", "profile_name"], as_dict=True
			)
			if profile and not profile.is_active:
				frappe.throw(
					f"DSC Profile '{profile.profile_name or self.profile}' is not active."
				)

	def on_update(self):
		# Once the signer has uploaded a PDF, picked a profile and placed the
		# signature box, create the DSC Signing Request that the standard
		# token-signing pipeline consumes. Idempotent — runs only while Draft.
		if self.status != "Draft":
			return
		if not (self.uploaded_pdf and self.profile and self.sig_width and self.sig_height):
			return
		self._create_signing_request()

	def _create_signing_request(self):
		"""Create (once) the Pending DSC Signing Request for this document."""
		existing = frappe.db.get_value(
			"DSC Signing Request",
			{
				"source_doctype": self.doctype,
				"source_name": self.name,
				"status": ["in", ["Pending", "In Progress"]],
			},
		)
		if existing:
			return existing

		sr = frappe.get_doc(
			{
				"doctype": "DSC Signing Request",
				"source_doctype": self.doctype,
				"source_name": self.name,
				"profile": self.profile,
				"signature_template": self.signature_template or None,
				"expected_signer_user": frappe.session.user,
				"status": "Pending",
				"created_on": now_datetime(),
			}
		).insert(ignore_permissions=True)

		# db_set (not save) so we don't re-trigger on_update.
		self.db_set("signing_request", sr.name, update_modified=False)
		self.db_set("status", "Pending", update_modified=False)
		return sr.name
