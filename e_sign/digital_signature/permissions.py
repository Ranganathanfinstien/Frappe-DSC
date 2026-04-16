"""
Permission hooks for DSC DocTypes.

Controls access so DSC Signers only see their own signing requests
and only profiles they're assigned to.
"""

import frappe


def request_has_permission(doc, ptype, user):
	"""Permission check for DSC Signing Request.

	- DSC Administrator / System Manager: full access
	- DSC Signer: can only access requests where they are the expected or actual signer
	- DSC Auditor: read-only access to all
	"""
	if ptype == "read":
		if "DSC Administrator" in frappe.get_roles(user):
			return True
		if "DSC Auditor" in frappe.get_roles(user):
			return True
		if "System Manager" in frappe.get_roles(user):
			return True
		if doc.expected_signer_user == user or doc.actual_signer_user == user:
			return True
		return False

	if ptype in ("write", "create"):
		if "DSC Administrator" in frappe.get_roles(user):
			return True
		if "System Manager" in frappe.get_roles(user):
			return True
		if "DSC Signer" in frappe.get_roles(user) and doc.expected_signer_user == user:
			return True
		return False

	return False


def profile_has_permission(doc, ptype, user):
	"""Permission check for DSC Profile.

	- DSC Administrator / System Manager: full access
	- DSC Signer: read-only if they are in allowed_users
	"""
	if "DSC Administrator" in frappe.get_roles(user):
		return True
	if "System Manager" in frappe.get_roles(user):
		return True

	if ptype == "read" and "DSC Signer" in frappe.get_roles(user):
		allowed_users = [row.user for row in doc.allowed_users]
		return user in allowed_users

	return False
