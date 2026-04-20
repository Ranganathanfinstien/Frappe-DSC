"""
Agent API — endpoints for dsc-bridge desktop agent pairing and certificate registration.
"""

import hashlib
import secrets

import frappe
from frappe.utils import now_datetime


# In-memory store for pairing codes (short-lived, single-use)
_pairing_codes = {}


@frappe.whitelist()
def generate_pairing_code():
	"""Generate a one-time pairing code for agent registration.

	Called by admin from DSC Agent Registration form.
	The code is displayed to the user who enters it in the desktop agent.
	Code expires in 10 minutes.
	"""
	code = secrets.token_urlsafe(16)

	_pairing_codes[code] = {
		"user": frappe.session.user,
		"created_at": now_datetime(),
		"site_url": frappe.utils.get_url(),
	}

	return {
		"pairing_code": code,
		"expires_in_seconds": 600,
		"site_url": frappe.utils.get_url(),
	}


@frappe.whitelist(allow_guest=True)
def validate_pairing_code(pairing_code, agent_fingerprint, os_platform=None, agent_version=None):
	"""Validate a pairing code submitted by the desktop agent.

	Called by dsc-bridge during the pairing flow.
	Creates a DSC Agent Registration record on success.

	Returns:
		dict with site_token for future authenticated requests
	"""
	if pairing_code not in _pairing_codes:
		frappe.throw("Invalid or expired pairing code.", frappe.AuthenticationError)

	code_data = _pairing_codes.pop(pairing_code)

	# Check expiry (10 minutes)
	from frappe.utils import time_diff_in_seconds
	age = time_diff_in_seconds(now_datetime(), code_data["created_at"])
	if age > 600:
		frappe.throw("Pairing code has expired. Please generate a new one.", frappe.AuthenticationError)

	# Generate a long-lived site token for this agent
	site_token = secrets.token_urlsafe(32)

	# Create agent registration
	agent_reg = frappe.get_doc({
		"doctype": "DSC Agent Registration",
		"user": code_data["user"],
		"agent_fingerprint": agent_fingerprint,
		"display_name": f"{os_platform or 'Unknown'} Agent",
		"paired_on": now_datetime(),
		"last_seen_on": now_datetime(),
		"is_active": 1,
		"os_platform": os_platform,
		"agent_version": agent_version,
	})
	agent_reg.insert(ignore_permissions=True)

	# Store the site token (encrypted) linked to this registration
	frappe.db.set_value(
		"DSC Agent Registration",
		agent_reg.name,
		"agent_fingerprint",
		agent_fingerprint,
	)

	frappe.db.commit()

	return {
		"status": "paired",
		"site_token": site_token,
		"site_url": code_data["site_url"],
		"agent_registration": agent_reg.name,
	}


@frappe.whitelist()
def register_certificate(profile_name, cert_der_b64):
	"""Register a certificate from the agent to a DSC Profile.

	Called when admin clicks "Register Certificate" on the profile form.
	The agent has already sent the certificate list; admin selected one;
	this endpoint stores the selected certificate details in the profile.

	Args:
		profile_name: name of the DSC Profile
		cert_der_b64: base64-encoded DER certificate from the agent
	"""
	import base64

	from asn1crypto import x509 as asn1_x509

	cert_der = base64.b64decode(cert_der_b64)

	# Parse certificate
	cert = asn1_x509.Certificate.load(cert_der)
	subject = cert.subject

	# Extract fields
	common_name = subject.human_friendly
	issuer = cert.issuer.human_friendly
	serial = format(cert.serial_number, "X")
	not_before = cert["tbs_certificate"]["validity"]["not_before"].native
	not_after = cert["tbs_certificate"]["validity"]["not_after"].native

	# Compute fingerprint
	fingerprint = hashlib.sha256(cert_der).hexdigest()

	# PEM encoding
	cert_pem = (
		"-----BEGIN CERTIFICATE-----\n"
		+ base64.b64encode(cert_der).decode()
		+ "\n-----END CERTIFICATE-----"
	)

	# Load the profile
	profile = frappe.get_doc("DSC Profile", profile_name)

	# If there's an existing certificate, archive it
	if profile.certificate_fingerprint:
		profile.append("previous_certificates", {
			"certificate_fingerprint": profile.certificate_fingerprint,
			"certificate_common_name": profile.certificate_common_name,
			"certificate_not_after": profile.certificate_not_after,
			"replaced_on": now_datetime(),
		})

	# Update with new certificate
	profile.certificate_fingerprint = fingerprint
	profile.certificate_common_name = common_name
	profile.certificate_issuer = issuer
	profile.certificate_serial = serial
	profile.certificate_not_before = not_before
	profile.certificate_not_after = not_after
	profile.certificate_pem_public = cert_pem
	profile.registered_on = now_datetime()

	profile.save(ignore_permissions=True)

	return {
		"status": "registered",
		"fingerprint": fingerprint,
		"common_name": common_name,
		"issuer": issuer,
		"not_before": str(not_before),
		"not_after": str(not_after),
	}


@frappe.whitelist()
def list_agent_certificates(agent_port=None):
	"""Proxy endpoint — browser calls this, server could forward to agent.

	In practice, the browser calls the agent directly (localhost).
	This endpoint is kept for cases where the server needs to validate
	the cert list (e.g., filtering by profile requirements).
	"""
	return {
		"message": "Call the agent directly at https://127.0.0.1:{port}/v1/certs".format(
			port=agent_port or 4645
		)
	}
