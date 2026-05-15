"""
DSC Signature Template controller.

Versioning rule (PRD §F3.6): once a template has been used by at least one
DSC Signing Request, it must not be edited destructively — instead, on save
we fork a new versioned copy that captures the in-progress edits, then revert
the in-place document to its prior state with is_active=0 so historical
signatures remain reproducible against the original template.
"""

import frappe
from frappe.model.document import Document


_VERSIONED_FIELDS = (
	"target_doctype",
	"print_format",
	"stamp_show_signer_name",
	"stamp_show_designation",
	"stamp_show_digitally_signed_by",
	"stamp_show_timestamp",
	"stamp_timestamp_format",
	"stamp_show_reason",
	"stamp_show_location",
	"stamp_show_dn_cn",
	"stamp_include_signature_image",
	"stamp_include_seal_image",
	"stamp_font_family",
	"stamp_font_size",
	"stamp_border",
)


class DSCSignatureTemplate(Document):
	def before_save(self):
		if self.is_new():
			if not self.version:
				self.version = 1
			return

		if not self._has_signing_history():
			return

		previous = self.get_doc_before_save()
		if not previous:
			return

		if not self._versioned_fields_changed(previous):
			return

		new_name = self._fork_new_version(previous)
		frappe.msgprint(
			f"This template has been used by signed documents and cannot be edited "
			f"in place. A new version <b>{new_name}</b> has been created with your "
			f"changes — the original is now inactive.",
			title="Template Versioned",
			indicator="orange",
		)

		# Roll the in-place doc back to its prior state and deactivate it
		for field in _VERSIONED_FIELDS:
			self.set(field, previous.get(field))
		self.fields = []
		for row in (previous.get("fields") or []):
			data = row.as_dict() if hasattr(row, "as_dict") else dict(row)
			for k in ("name", "owner", "creation", "modified", "modified_by",
					  "parent", "parenttype", "parentfield"):
				data.pop(k, None)
			self.append("fields", data)
		self.is_active = 0

	def _has_signing_history(self):
		return bool(
			frappe.db.exists(
				"DSC Signing Request",
				{"signature_template": self.name},
			)
		)

	def _versioned_fields_changed(self, previous):
		for field in _VERSIONED_FIELDS:
			if (self.get(field) or "") != (previous.get(field) or ""):
				return True

		old_rows = [
			(r.field_name, r.page_number, r.x, r.y, r.width, r.height, r.assigned_profile)
			for r in (previous.get("fields") or [])
		]
		new_rows = [
			(r.field_name, r.page_number, r.x, r.y, r.width, r.height, r.assigned_profile)
			for r in (self.fields or [])
		]
		return old_rows != new_rows

	def _fork_new_version(self, previous):
		new_doc = frappe.new_doc("DSC Signature Template")
		new_doc.template_name = f"{previous.template_name} v{(previous.version or 1) + 1}"
		new_doc.version = (previous.version or 1) + 1
		new_doc.is_active = 1

		for field in _VERSIONED_FIELDS:
			new_doc.set(field, self.get(field))

		for row in (self.fields or []):
			data = row.as_dict() if hasattr(row, "as_dict") else dict(row)
			for k in ("name", "owner", "creation", "modified", "modified_by",
					  "parent", "parenttype", "parentfield"):
				data.pop(k, None)
			new_doc.append("fields", data)

		new_doc.insert(ignore_permissions=True)
		return new_doc.name
