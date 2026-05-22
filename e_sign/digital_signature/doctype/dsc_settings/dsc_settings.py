"""DSC Settings — single doctype for global signing configuration."""

import secrets

import frappe
from frappe.model.document import Document


class DSCSettings(Document):
	pass


def get_or_create_hmac_secret():
	"""Return the HMAC secret used to sign /v1/sign payloads.

	Auto-generates one on first call so admins don't need to set it manually.
	Stored encrypted via the Password fieldtype (Frappe handles encryption
	at rest with the site's encryption_key).

	Rotation: clear the field via DSC Settings UI; next call regenerates.
	"""
	doc = frappe.get_single("DSC Settings")
	# get_password returns the decrypted value from the *Auth table; it returns
	# None if unset.
	current = doc.get_password("hmac_secret", raise_exception=False) if doc.hmac_secret else None
	if current:
		return current

	new_secret = secrets.token_urlsafe(48)
	doc.hmac_secret = new_secret
	doc.save(ignore_permissions=True)
	# persist the freshly generated HMAC
	# secret before it is returned to the caller; the agent will use it to sign
	# subsequent requests, so the stored value must be durable first.
	frappe.db.commit()  # nosemgrep: frappe-manual-commit
	return new_secret
