"""
Post-install setup for the e_sign app (PRD §12.6).

Adds a Custom Field `is_dsc_signed` to the core File doctype so signed PDFs
can be tracked and protected from deletion by non-DSC-Administrators.
"""

import frappe


def after_install():
	_ensure_is_dsc_signed_custom_field()


def _ensure_is_dsc_signed_custom_field():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	create_custom_field(
		"File",
		{
			"fieldname": "is_dsc_signed",
			"label": "DSC Signed",
			"fieldtype": "Check",
			"default": 0,
			"read_only": 1,
			"in_list_view": 0,
			"description": "Set to 1 by the DSC signing engine when this File is the output of a successful DSC signing flow.",
			"insert_after": "is_private",
		},
	)
