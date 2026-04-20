"""
Print Gate — intercepts PDF downloads to enforce signing requirements.

When a DSC Rule has block_print_until_signed=1 for a DocType:
  - If a signed PDF exists → serve the signed version instead
  - If not signed yet and mandatory → block with error
  - Otherwise → pass through to the original Frappe print
"""

import frappe


def download_pdf(doctype, name, format=None, doc=None, no_letterhead=0, language=None, letterhead=None):
	"""Override of frappe.utils.print_format.download_pdf.

	Checks DSC Rules for the document and either:
	1. Substitutes the signed PDF if available
	2. Blocks the download if signing is mandatory but not done
	3. Passes through to original Frappe PDF generation
	"""
	from frappe.utils.print_format import download_pdf as _original_download_pdf

	# Check if any DSC Rule with block_print_until_signed applies
	blocking_rule = frappe.db.get_value(
		"DSC Rule",
		filters={
			"target_doctype": doctype,
			"is_enabled": 1,
			"block_print_until_signed": 1,
		},
		fieldname=["name", "is_mandatory"],
		as_dict=True,
	)

	if not blocking_rule:
		# No blocking rule — pass through
		return _original_download_pdf(
			doctype, name, format=format, doc=doc,
			no_letterhead=no_letterhead, language=language, letterhead=letterhead,
		)

	# Check if a signed PDF exists for this document
	signed_request = frappe.db.get_value(
		"DSC Signing Request",
		filters={
			"source_doctype": doctype,
			"source_name": name,
			"status": "Signed",
		},
		fieldname=["name", "signed_file"],
		as_dict=True,
	)

	if signed_request and signed_request.signed_file:
		# Serve the signed PDF instead of generating a new one
		file_doc = frappe.get_doc("File", signed_request.signed_file)
		file_content = file_doc.get_content()

		frappe.local.response.filename = file_doc.file_name
		frappe.local.response.filecontent = file_content
		frappe.local.response.type = "download"
		return

	# No signed PDF exists
	if blocking_rule.is_mandatory:
		frappe.throw(
			f"This {doctype} requires a digital signature before printing. "
			f"Please sign the document first using 'Sign with DSC'.",
			title="Signature Required",
		)

	# Not mandatory — let the original print through
	return _original_download_pdf(
		doctype, name, format=format, doc=doc,
		no_letterhead=no_letterhead, language=language, letterhead=letterhead,
	)
