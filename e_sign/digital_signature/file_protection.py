"""
File protection — refuses deletion of DSC-signed PDFs by non-administrators.

Wired in hooks.py via doc_events on File.before_delete (PRD §12.6).
"""

import frappe


def before_delete(doc, method=None):
	if not getattr(doc, "is_dsc_signed", 0):
		return

	user_roles = set(frappe.get_roles(frappe.session.user))
	if {"DSC Administrator", "System Manager", "Administrator"} & user_roles:
		return

	frappe.throw(
		"This file is a DSC-signed PDF and cannot be deleted. "
		"Contact a DSC Administrator if removal is required.",
		title="Protected — DSC Signed",
	)
