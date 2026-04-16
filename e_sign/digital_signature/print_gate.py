"""
Print Gate — intercepts PDF downloads to enforce signing requirements.

This module is owned by Ranga. Stub implementation passes through to
Frappe's default download_pdf until the gating logic is built.
"""

import frappe
from frappe.utils.print_format import download_pdf as _original_download_pdf


def download_pdf(doctype, name, format=None, doc=None, no_letterhead=0, language=None, letterhead=None):
	"""Override of frappe.utils.print_format.download_pdf.

	Once implemented, this will:
	1. Check if a DSC Rule with block_print_until_signed=1 exists for this doc
	2. If signed PDF exists, serve that instead
	3. If not signed and mandatory, block with error
	4. Otherwise, pass through to original
	"""
	return _original_download_pdf(
		doctype, name, format=format, doc=doc,
		no_letterhead=no_letterhead, language=language, letterhead=letterhead
	)
