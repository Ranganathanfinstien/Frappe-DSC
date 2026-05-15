"""
Email Gate — blocks email sending for documents that require signing.

When a DSC Rule has block_email_until_signed=1:
  - If the document has a signed PDF → allow email, auto-attach signed PDF
  - If not signed yet → block with error message

Wired in hooks.py via override_whitelisted_methods on
frappe.core.doctype.communication.email.make so every Communication-style
email (including the Send Email dialog on every doctype) flows through here.
"""

import frappe


@frappe.whitelist()
def make(**kwargs):
	"""Drop-in replacement for frappe.core.doctype.communication.email.make.

	Performs the DSC gate check, optionally augments attachments with the
	signed PDF, then delegates to the original implementation. Kept signature
	loose (**kwargs) so it tolerates Frappe upgrades that add parameters.
	"""
	from frappe.core.doctype.communication.email import make as _original_make

	doctype = kwargs.get("doctype")
	docname = kwargs.get("name")

	if doctype and docname:
		check_email_allowed(doctype, docname)

		# If a signed PDF exists for this doc, auto-attach it. This honours
		# the PRD requirement that emailed copies use the signed version once
		# signing has happened (PRD §12.4).
		signed_file = get_signed_pdf_for_attachment(doctype, docname)
		if signed_file is not None:
			existing = kwargs.get("attachments") or []
			# Skip if already attached
			already_attached = any(
				(isinstance(a, dict) and a.get("fid") == signed_file.name)
				or (isinstance(a, str) and a == signed_file.name)
				for a in existing
			)
			if not already_attached:
				kwargs["attachments"] = list(existing) + [{"fid": signed_file.name}]

	return _original_make(**kwargs)


def check_email_allowed(doctype, docname):
	"""Check if emailing is allowed for this document.

	Returns silently if allowed; throws if a DSC Rule blocks email until signed
	and no signed version exists yet.
	"""
	blocking_rule = frappe.db.get_value(
		"DSC Rule",
		filters={
			"target_doctype": doctype,
			"is_enabled": 1,
			"block_email_until_signed": 1,
		},
		fieldname="name",
	)

	if not blocking_rule:
		return True

	signed = frappe.db.exists(
		"DSC Signing Request",
		{
			"source_doctype": doctype,
			"source_name": docname,
			"status": "Signed",
		},
	)

	if signed:
		return True

	frappe.throw(
		f"This {doctype} requires a digital signature before it can be emailed. "
		f"Please sign the document first using 'Sign with DSC'.",
		title="Signature Required",
	)


def get_signed_pdf_for_attachment(doctype, docname):
	"""Get the signed PDF File doc for attaching to emails.

	Returns the File doc if a signed PDF exists, None otherwise.
	"""
	signed_file_name = frappe.db.get_value(
		"DSC Signing Request",
		filters={
			"source_doctype": doctype,
			"source_name": docname,
			"status": "Signed",
		},
		fieldname="signed_file",
	)

	if signed_file_name:
		return frappe.get_doc("File", signed_file_name)

	return None
