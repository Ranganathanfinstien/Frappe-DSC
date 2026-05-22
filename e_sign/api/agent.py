"""
Agent API — endpoints for dsc-bridge desktop agent pairing and certificate registration.
"""

import hashlib
import hmac
import secrets

import frappe
from frappe.utils import now_datetime


# Pairing codes are stored in Frappe's Redis cache so they survive worker
# restarts and work across gunicorn workers (a process-local dict would be
# lost on reload and invisible to other workers).
_PAIRING_KEY_PREFIX = "e_sign:pairing:"
_PAIRING_TTL_SECONDS = 600  # 10 minutes


def _pairing_key(code):
	return _PAIRING_KEY_PREFIX + code


def _hash_token(token):
	"""SHA-256 hash for storing a long-lived site token at rest."""
	return hashlib.sha256(token.encode("utf-8")).hexdigest()


@frappe.whitelist()
def generate_pairing_code():
	"""Generate a one-time pairing code for agent registration.

	Called by admin from DSC Agent Registration form.
	The code is displayed to the user who enters it in the desktop agent.
	Code expires in 10 minutes.
	"""
	import json

	# Use the URL the browser actually reached us on (Host / X-Forwarded-Host)
	# instead of frappe.utils.get_url(), which resolves to the server-internal
	# host_name. The agent must call back through the public-facing URL.
	def _public_site_url():
		req = getattr(frappe.local, "request", None)
		if req is not None:
			xfh = req.headers.get("X-Forwarded-Host") or req.headers.get("X-Original-Host")
			host = xfh or req.host
			proto = req.headers.get("X-Forwarded-Proto") or ("https" if req.is_secure else "http")
			if host:
				return f"{proto}://{host}"
		return frappe.utils.get_url()

	site_url = _public_site_url()
	code = secrets.token_urlsafe(16)
	payload = {
		"user": frappe.session.user,
		"created_at": str(now_datetime()),
		"site_url": site_url,
	}

	frappe.cache().set_value(
		_pairing_key(code),
		json.dumps(payload),
		expires_in_sec=_PAIRING_TTL_SECONDS,
	)

	return {
		"pairing_code": code,
		"expires_in_seconds": _PAIRING_TTL_SECONDS,
		"site_url": site_url,
	}


@frappe.whitelist(allow_guest=True)
def validate_pairing_code(pairing_code, agent_fingerprint, os_platform=None, agent_version=None):
	"""Validate a pairing code submitted by the desktop agent.

	Called by dsc-bridge during the pairing flow.
	Creates a DSC Agent Registration record on success.

	Returns:
		dict with site_token for future authenticated requests
	"""
	import json

	key = _pairing_key(pairing_code)
	raw = frappe.cache().get_value(key)
	if not raw:
		frappe.throw("Invalid or expired pairing code.", frappe.AuthenticationError)

	# One-time use: invalidate immediately
	frappe.cache().delete_value(key)

	if isinstance(raw, bytes):
		raw = raw.decode("utf-8")
	code_data = json.loads(raw)

	# Generate a long-lived site token for this agent. Store only the hash;
	# the plaintext is returned once to the agent and never persisted.
	site_token = secrets.token_urlsafe(32)
	site_token_hash = _hash_token(site_token)

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
		"site_token_hash": site_token_hash,
	})
	agent_reg.insert(ignore_permissions=True)

	# persist agent registration before the
	# one-time token is returned to the client; if the response fails later we
	# must not hand out a token that has no durable registration.
	frappe.db.commit()  # nosemgrep: frappe-manual-commit

	# Provide the server-side HMAC secret to the agent so it can verify HMAC
	# tags on subsequent /v1/sign requests (PRD §13.4 / §17.1). The plaintext
	# is delivered exactly once at pair time.
	from e_sign.digital_signature.doctype.dsc_settings.dsc_settings import (
		get_or_create_hmac_secret,
	)
	hmac_secret = get_or_create_hmac_secret()

	return {
		"status": "paired",
		"site_token": site_token,
		"site_url": code_data["site_url"],
		"agent_registration": agent_reg.name,
		"hmac_secret": hmac_secret,
	}


@frappe.whitelist(allow_guest=True)
def verify_site_token(site_token, agent_fingerprint=None):
	"""Look up an active agent registration by hashed site token.

	Used by future endpoints that authenticate the agent (e.g. HMAC verification
	on /v1/sign payloads). Constant-time hash comparison.
	"""
	if not site_token:
		return None

	token_hash = _hash_token(site_token)
	filters = {"site_token_hash": token_hash, "is_active": 1}
	if agent_fingerprint:
		filters["agent_fingerprint"] = agent_fingerprint

	agent_name = frappe.db.get_value("DSC Agent Registration", filters, "name")
	if not agent_name:
		return None

	# Touch last_seen_on for liveness telemetry
	frappe.db.set_value("DSC Agent Registration", agent_name, "last_seen_on", now_datetime())
	return agent_name


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

	cert = asn1_x509.Certificate.load(cert_der)
	subject = cert.subject

	common_name = subject.human_friendly
	issuer = cert.issuer.human_friendly
	serial = format(cert.serial_number, "X")
	not_before = cert["tbs_certificate"]["validity"]["not_before"].native
	not_after = cert["tbs_certificate"]["validity"]["not_after"].native

	fingerprint = hashlib.sha256(cert_der).hexdigest()

	cert_pem = (
		"-----BEGIN CERTIFICATE-----\n"
		+ base64.b64encode(cert_der).decode()
		+ "\n-----END CERTIFICATE-----"
	)

	profile = frappe.get_doc("DSC Profile", profile_name)

	if profile.certificate_fingerprint:
		profile.append("previous_certificates", {
			"certificate_fingerprint": profile.certificate_fingerprint,
			"certificate_common_name": profile.certificate_common_name,
			"certificate_not_after": profile.certificate_not_after,
			"replaced_on": now_datetime(),
		})

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
