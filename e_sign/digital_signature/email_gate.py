"""
Email Gate — blocks email sending for documents that require signing.

When a DSC Rule has block_email_until_signed=1:
  - If the document has a signed PDF → allow email, auto-attach signed PDF
  - If not signed yet → block with error message
"""

import frappe


def check_email_allowed(doctype, docname):
	"""Check if emailing is allowed for this document.

	Called before sending email. Returns True if allowed, throws if blocked.
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

	# Check if a signed version exists
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
	"""Get the signed PDF file doc for attaching to emails.

	Returns the File doc if a signed PDF exists, None otherwise.
	"""
	signed_request = frappe.db.get_value(
		"DSC Signing Request",
		filters={
			"source_doctype": doctype,
			"source_name": docname,
			"status": "Signed",
		},
		fieldname="signed_file",
	)

	if signed_request:
		return frappe.get_doc("File", signed_request)

	return None
