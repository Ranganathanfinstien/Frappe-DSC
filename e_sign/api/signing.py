"""
Server API for DSC signing workflow.

These whitelisted endpoints are called by the browser JavaScript
to orchestrate the three-way signing flow:
  Browser → Server (initiate) → Browser → Agent (sign) → Browser → Server (finalize)
"""

import frappe
from frappe.utils import now_datetime, time_diff_in_seconds


def _run_dev_hooks(hook_name, **kwargs):
	"""Invoke developer hooks declared in other apps' hooks.py.

	Apps may register handlers like:
	    dsc_before_sign  = "myapp.dsc_hooks.before_sign"
	    dsc_after_sign   = "myapp.dsc_hooks.after_sign"
	    dsc_on_decline   = "myapp.dsc_hooks.on_decline"

	Each handler receives the kwargs as named arguments. Failures are logged
	but never roll back the signing flow.
	"""
	for handler in frappe.get_hooks(hook_name) or []:
		try:
			frappe.get_attr(handler)(**kwargs)
		except Exception:
			frappe.log_error(title=f"DSC dev hook {hook_name} -> {handler} failed")


def _read_uploaded_pdf(file_url):
	"""Return the raw bytes of the PDF attached to a DSC Document Sign record."""
	if not file_url:
		frappe.throw("No PDF has been uploaded on this document.")
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	content = file_doc.get_content()
	if isinstance(content, str):
		# A PDF read as text — re-encode preserving every byte.
		content = content.encode("latin-1")
	if not content or not content[:5].startswith(b"%PDF"):
		frappe.throw("The uploaded file is not a valid PDF.")
	return content


@frappe.whitelist()
def initiate(doctype, docname, cert_der_b64, signer_lat=None, signer_lng=None, signer_accuracy_m=None):
	# Frappe form_dict serializes JSON null as empty string. Normalise so the
	# `is None` checks downstream behave correctly.
	if signer_lat in ("", "null", "None"):
		signer_lat = None
	if signer_lng in ("", "null", "None"):
		signer_lng = None
	if signer_accuracy_m in ("", "null", "None"):
		signer_accuracy_m = None
	if not cert_der_b64:
		frappe.throw("Signer certificate is required (cert_der_b64 was empty). The browser must fetch it from the bridge before calling initiate.")


	"""Start the signing process for a document.

	Called when the signer clicks "Sign with DSC".
	1. Validates permissions
	2. Enforces signer location capture (if enabled in DSC Settings)
	3. Finds the pending DSC Signing Request
	4. Reverse-geocodes signer coordinates into a readable address
	5. Calls signing_engine to prepare PDF and compute hash
	6. Returns session_id + hash for the browser to send to the agent

	Returns:
		dict: {session_id, hash_to_sign, hash_algorithm, expected_cert_fingerprint, visual_metadata}
	"""
	from e_sign.digital_signature.audit import log_event
	from e_sign.digital_signature.geocoding import reverse_geocode
	from e_sign.digital_signature.signing_engine import prepare_pdf_for_signing

	# Find a pending signing request for this document
	signing_request = frappe.db.get_value(
		"DSC Signing Request",
		filters={
			"source_doctype": doctype,
			"source_name": docname,
			"status": "Pending",
		},
		fieldname=["name", "profile", "signature_template", "expected_signer_user"],
		as_dict=True,
	)

	if not signing_request:
		frappe.throw(f"No pending signing request found for {doctype} {docname}")

	# Validate the current user is the expected signer
	if signing_request.expected_signer_user and signing_request.expected_signer_user != frappe.session.user:
		if not frappe.has_permission("DSC Signing Request", "write"):
			frappe.throw("You are not authorized to sign this document.")

	# Load profile and template
	profile = frappe.get_doc("DSC Profile", signing_request.profile)
	if not profile.is_active:
		frappe.throw(f"DSC Profile '{profile.profile_name}' is not active.")

	# Enforce profile-level signing allowlist. The allowed_users table on a
	# DSC Profile is the boss's authorised-delegates list — only those users
	# may sign with this profile/token, regardless of their role. Empty list =
	# legacy / unrestricted profile (kept permissive for backwards compatibility).
	allowed = [row.user for row in (profile.allowed_users or []) if row.user]
	if allowed and frappe.session.user not in allowed:
		frappe.throw(
			f"You are not authorised to sign with DSC Profile "
			f"'{profile.profile_name}'. The profile owner has restricted "
			f"signing to a specific list of users."
		)

	# Check certificate expiry
	if profile.certificate_not_after:
		from frappe.utils import getdate
		if getdate(profile.certificate_not_after) < getdate(now_datetime()):
			frappe.throw(
				f"Certificate for profile '{profile.profile_name}' expired on "
				f"{profile.certificate_not_after}. Please renew."
			)

	# Enforce signer location capture (server-side: cannot be bypassed by tampered JS).
	# Compliance requirement — every signature must carry the signer's geographic
	# position at the moment of signing, for legal evidence purposes.
	settings = frappe.get_single("DSC Settings")
	enforce_location = bool(getattr(settings, "enforce_signer_location", 1))
	if enforce_location and (signer_lat is None or signer_lng is None):
		frappe.throw(
			"Location access is required to digitally sign documents. "
			"Please allow your browser to share its location and try again."
		)

	geocode_result = None
	if signer_lat is not None and signer_lng is not None:
		geocode_result = reverse_geocode(signer_lat, signer_lng)

	# Load signature template (may be None for rules without template)
	sig_template = None
	if signing_request.signature_template:
		sig_template = frappe.get_doc("DSC Signature Template", signing_request.signature_template)
	else:
		# Create a minimal template with default placement
		sig_template = frappe.new_doc("DSC Signature Template")
		sig_template.stamp_show_signer_name = 1
		sig_template.stamp_show_designation = 1
		sig_template.stamp_show_digitally_signed_by = 1
		sig_template.stamp_show_timestamp = 1
		sig_template.stamp_show_reason = 1
		sig_template.stamp_show_location = 1

	# Ad-hoc uploaded-document signing: when the source is a DSC Document Sign
	# record, the bytes to sign are the user's uploaded PDF and the signature
	# box comes from the placement they made interactively — not a print
	# format or a saved signature template.
	uploaded_pdf_bytes = None
	placement = None
	if doctype == "DSC Document Sign":
		doc_sign = frappe.get_doc(doctype, docname)
		uploaded_pdf_bytes = _read_uploaded_pdf(doc_sign.uploaded_pdf)
		if not (doc_sign.sig_width and doc_sign.sig_height):
			frappe.throw(
				"No signature position has been set. Open the document, drag the "
				"signature box onto the page, and save before signing."
			)
		placement = {
			"page": doc_sign.sig_page or 1,
			"x": doc_sign.sig_x or 0,
			"y": doc_sign.sig_y or 0,
			"width": doc_sign.sig_width,
			"height": doc_sign.sig_height,
		}
		doc_sign.db_set("status", "In Progress", update_modified=False)

	# Get print format from the rule (skipped for uploaded documents)
	print_format = None
	if uploaded_pdf_bytes is None:
		if signing_request.get("rule"):
			rule = frappe.get_doc("DSC Rule", signing_request.rule)
			print_format = rule.print_format

		if not print_format:
			# Use the DocType's default print format (field lives on DocType, not Print Format)
			print_format = frappe.db.get_value("DocType", doctype, "default_print_format")
			if not print_format:
				print_format = "Standard"

	# Update request status to In Progress
	request_updates = {
		"status": "In Progress",
		"client_ip": getattr(frappe.local, "request_ip", None),
		"client_user_agent": (
			frappe.local.request.headers.get("User-Agent", "")
			if getattr(frappe.local, "request", None) else None
		),
	}
	if signer_lat is not None and signer_lng is not None:
		request_updates.update({
			"signer_lat": float(signer_lat),
			"signer_lng": float(signer_lng),
			"signer_accuracy_m": float(signer_accuracy_m) if signer_accuracy_m is not None else None,
			"signer_address": (geocode_result or {}).get("address") or "",
			"signer_location_provider": (geocode_result or {}).get("provider") or "",
		})
	frappe.db.set_value("DSC Signing Request", signing_request.name, request_updates)

	# Developer hook: dsc_before_sign — gives third-party apps a chance to
	# attach metadata, run validations, etc. Hook may raise to abort.
	_run_dev_hooks(
		"dsc_before_sign",
		signing_request=signing_request.name,
		doctype=doctype,
		docname=docname,
		profile=signing_request.profile,
	)

	# Prepare PDF and compute hash. The signer's resolved address (if any)
	# is passed through so the PDF Location field and visible stamp reflect
	# where the signer actually was, not a static admin-configured string.
	signer_location_text = (geocode_result or {}).get("address") if geocode_result else None
	import base64 as _b64
	import hashlib as _hashlib_local

	cert_der = _b64.b64decode(cert_der_b64)
	cert_fp = _hashlib_local.sha256(cert_der).hexdigest()
	if profile.certificate_fingerprint and cert_fp != profile.certificate_fingerprint:
		frappe.throw(
			f"Certificate on token does not match the one registered on DSC Profile {profile.name}. "
			f"Expected fingerprint {profile.certificate_fingerprint[:16]}…, got {cert_fp[:16]}…."
		)

	result = prepare_pdf_for_signing(
		doctype=doctype,
		docname=docname,
		print_format=print_format,
		sig_template=sig_template,
		profile=profile,
		signing_request_name=signing_request.name,
		cert_der=cert_der,
		signer_location_text=signer_location_text,
		pdf_bytes=uploaded_pdf_bytes,
		placement=placement,
	)

	# Update request with hash
	frappe.db.set_value("DSC Signing Request", signing_request.name, {
		"hash_algorithm": result["hash_algorithm"],
		"hash_to_be_signed": result["hash_to_sign"],
	})

	# Log audit events
	if geocode_result is not None:
		log_event(signing_request.name, "Signer Location Captured", {
			"lat": float(signer_lat),
			"lng": float(signer_lng),
			"accuracy_m": float(signer_accuracy_m) if signer_accuracy_m is not None else None,
			"address": geocode_result.get("address"),
			"provider": geocode_result.get("provider"),
			"geocode_ok": geocode_result.get("ok"),
		})

	log_event(signing_request.name, "Hash Computed", {
		"algorithm": result["hash_algorithm"],
		"hash_preview": result["hash_to_sign"][:16] + "...",
	})

	# PRD §F7.2 — Agent Called: server has prepared the hash and is handing
	# off control to the browser to call the local agent.
	log_event(signing_request.name, "Agent Called", {
		"agent_port": settings.agent_listen_port or 4645,
		"hash_algorithm": result["hash_algorithm"],
	})

	# PRD §13.4 / §17.1 — HMAC + replay protection.
	# Server computes HMAC-SHA256(hmac_secret, session_id|hash|hash_algo|timestamp|nonce).
	# Bridge verifies the same. Browser is a transparent proxy that cannot forge
	# this without the secret (which lives only on server + paired agent).
	import hmac as _hmac
	import hashlib as _hashlib
	import secrets as _secrets

	from e_sign.digital_signature.doctype.dsc_settings.dsc_settings import (
		get_or_create_hmac_secret,
	)

	hmac_secret = get_or_create_hmac_secret()
	timestamp = int(now_datetime().timestamp())
	nonce = _secrets.token_hex(16)
	mac_payload = "|".join([
		result["session_id"],
		result["hash_to_sign"],
		result["hash_algorithm"],
		str(timestamp),
		nonce,
	]).encode("utf-8")
	mac = _hmac.new(hmac_secret.encode("utf-8"), mac_payload, _hashlib.sha256).hexdigest()

	# Build response
	return {
		"session_id": result["session_id"],
		"hash_to_sign": result["hash_to_sign"],
		"hash_algorithm": result["hash_algorithm"],
		"expected_cert_fingerprint": profile.certificate_fingerprint,
		"signing_request": signing_request.name,
		"timestamp": timestamp,
		"nonce": nonce,
		"hmac": mac,
		"visual_metadata": {
			"signer_name": profile.certificate_common_name or profile.label,
			"reason": settings.default_reason or "Approved",
			"location": signer_location_text or settings.default_location or "",
		},
	}


@frappe.whitelist()
def finalize(session_id, signature_bytes_b64, cert_der_b64, cert_chain_der_b64=None, ocsp_der_b64=None):
	"""Complete the signing process after the agent returns the signature.

	Called by the browser after receiving the signature from the desktop agent.
	1. Injects signature into PDF via signing_engine
	2. Verifies the signed PDF
	3. Attaches signed PDF to source document
	4. Updates signing request status
	5. Logs audit events

	Returns:
		dict: {status, file_url, signing_request}
	"""
	import json

	from e_sign.digital_signature.audit import log_event
	from e_sign.digital_signature.signing_engine import (
		finalize_signed_pdf,
		get_session_info,
		save_signed_pdf,
		verify_signed_pdf,
	)

	# Validate session exists
	session = get_session_info(session_id)
	if not session:
		frappe.throw("Signing session expired or not found. Please try again.")

	signing_request_name = session["signing_request_name"]
	start_time = now_datetime()

	# Compute fingerprint of the certificate the agent returned and verify it
	# matches the profile *before* trusting any further input. The agent already
	# enforces this client-side, but the server must not trust the agent.
	import base64
	import hashlib as _hashlib

	cert_der_for_fp = base64.b64decode(cert_der_b64) if cert_der_b64 else b""
	presented_fingerprint = _hashlib.sha256(cert_der_for_fp).hexdigest() if cert_der_for_fp else None

	# Log that we received the signature from the agent
	log_event(signing_request_name, "Signature Returned", {
		"cert_fingerprint": presented_fingerprint,
		"has_chain": bool(cert_chain_der_b64),
		"has_ocsp": bool(ocsp_der_b64),
	})

	# Cert Presented event — separate from Signature Returned per PRD §F7.2
	log_event(signing_request_name, "Cert Presented", {
		"fingerprint": presented_fingerprint,
	})

	# Enforce server-side fingerprint binding (PRD §F2.4)
	req_doc = frappe.get_doc("DSC Signing Request", signing_request_name)
	expected_fp = (
		frappe.db.get_value("DSC Profile", req_doc.profile, "certificate_fingerprint")
		if req_doc.profile
		else None
	)
	if expected_fp and presented_fingerprint and expected_fp.lower() != presented_fingerprint.lower():
		frappe.db.set_value("DSC Signing Request", signing_request_name, {
			"status": "Failed",
			"failure_reason": "Certificate fingerprint mismatch — token cert does not match profile",
		})
		log_event(signing_request_name, "Request Failed", {
			"reason": "Fingerprint mismatch",
			"expected": expected_fp,
			"presented": presented_fingerprint,
		})
		# persist Failed status + audit event
		# before frappe.throw rolls back the request transaction; the evidence
		# trail must survive the abort.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		frappe.throw(
			"The certificate on the token does not match this profile. "
			"Pair the correct token or contact a DSC Administrator."
		)

	# Parse cert_chain from JSON if it came as a string
	if isinstance(cert_chain_der_b64, str):
		try:
			cert_chain_der_b64 = json.loads(cert_chain_der_b64)
		except (json.JSONDecodeError, TypeError):
			cert_chain_der_b64 = [cert_chain_der_b64] if cert_chain_der_b64 else []

	try:
		# Finalize the signed PDF
		signed_result = finalize_signed_pdf(
			session_id=session_id,
			signature_bytes_b64=signature_bytes_b64,
			cert_der_b64=cert_der_b64,
			cert_chain_der_b64=cert_chain_der_b64,
			ocsp_der_b64=ocsp_der_b64,
		)

		# Verify the signed PDF
		verification = verify_signed_pdf(signed_result["signed_pdf_bytes"])
		log_event(signing_request_name, "PDF Verified", {
			"is_valid": verification.get("is_valid"),
			"signature_count": verification.get("signature_count"),
		})

		if not verification.get("is_valid") and not verification.get("signatures"):
			# Complete failure — no signatures at all
			frappe.db.set_value("DSC Signing Request", signing_request_name, {
				"status": "Failed",
				"failure_reason": f"Signed PDF verification failed: {verification.get('error', 'Unknown')}",
			})
			log_event(signing_request_name, "Request Failed", {
				"reason": "PDF verification failed",
				"details": verification,
			})
			frappe.throw("Signed PDF verification failed. The signature may be invalid.")

		# Save the signed PDF as attachment
		file_doc = save_signed_pdf(signed_result)

		# Calculate duration
		duration = int(time_diff_in_seconds(now_datetime(), start_time))

		# Update signing request — store full evidence per PRD §11.7 (Long Text fields)
		frappe.db.set_value("DSC Signing Request", signing_request_name, {
			"status": "Signed",
			"actual_signer_user": frappe.session.user,
			"signed_on": now_datetime(),
			"sign_duration_seconds": duration,
			"signature_bytes": signature_bytes_b64,
			"certificate_fingerprint_presented": signed_result.get("certificate_fingerprint"),
			"ocsp_response_b64": ocsp_der_b64,
			"signed_file": file_doc.name,
		})

		# Mirror the outcome onto the DSC Document Sign record, when that's the
		# source — keeps its status and signed-PDF link in step with the request.
		if signed_result["doctype"] == "DSC Document Sign":
			frappe.db.set_value("DSC Document Sign", signed_result["docname"], {
				"status": "Signed",
				"signed_file": file_doc.name,
			})

		# Log success
		log_event(signing_request_name, "Request Signed", {
			"duration_seconds": duration,
			"file_name": file_doc.file_name,
			"file_size": len(signed_result["signed_pdf_bytes"]),
		})

		# Add timeline entry to source document
		add_timeline_entry(
			signed_result["doctype"],
			signed_result["docname"],
			signing_request_name,
		)

		# Send notification to document creator. Email failures must NOT roll back
		# the signing — the PDF is already signed and saved at this point.
		try:
			send_signed_notification(
				signed_result["doctype"],
				signed_result["docname"],
				signing_request_name,
			)
		except Exception:
			frappe.log_error(title="DSC: signed notification email failed")

		# commit the signed evidence (PDF +
		# audit events) before invoking external dev hooks; a hook failure must
		# not roll back a successful, legally-binding signature.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

		# Developer hook: dsc_after_sign — fires after evidence is committed.
		_run_dev_hooks(
			"dsc_after_sign",
			signing_request=signing_request_name,
			doctype=signed_result["doctype"],
			docname=signed_result["docname"],
			file_url=file_doc.file_url,
		)

		return {
			"status": "Signed",
			"file_url": file_doc.file_url,
			"file_name": file_doc.file_name,
			"signing_request": signing_request_name,
			"verification": verification,
		}

	except Exception as e:
		# Log failure
		frappe.db.set_value("DSC Signing Request", signing_request_name, {
			"status": "Failed",
			"failure_reason": str(e)[:500],
		})
		if req_doc.source_doctype == "DSC Document Sign":
			frappe.db.set_value(
				"DSC Document Sign", req_doc.source_name, "status", "Failed"
			)
		log_event(signing_request_name, "Request Failed", {
			"reason": str(e),
			"error_type": type(e).__name__,
		})
		# PRD §F8.3 — notify DSC Administrators on failure so they can act
		try:
			notify_admins_of_failure(signing_request_name, str(e))
		except Exception:
			frappe.log_error(title="DSC: admin failure-notification email failed")
		# persist Failed status + audit event
		# before `raise` triggers the request rollback; the evidence trail must
		# survive the abort.
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		raise


@frappe.whitelist()
def get_signing_status(doctype, docname):
	"""Get the current signing status of a document.

	Called by the frontend JS on form load to show status indicators.

	Returns:
		dict: {status, signing_requests, can_sign}
	"""
	requests = frappe.get_all(
		"DSC Signing Request",
		filters={
			"source_doctype": doctype,
			"source_name": docname,
		},
		fields=["name", "status", "profile", "expected_signer_user", "signed_on", "signed_file"],
		order_by="creation desc",
	)

	if not requests:
		return {"status": "Not Applicable", "signing_requests": [], "can_sign": False}

	# Determine overall status
	statuses = [r.status for r in requests]
	if all(s == "Signed" for s in statuses):
		overall = "Signed"
	elif any(s == "In Progress" for s in statuses):
		overall = "Signature In Progress"
	elif any(s == "Failed" for s in statuses):
		overall = "Signing Failed"
	elif any(s == "Pending" for s in statuses):
		overall = "Awaiting Signature"
	else:
		overall = "Not Applicable"

	# Can current user sign?
	can_sign = any(
		r.status == "Pending" and r.expected_signer_user == frappe.session.user
		for r in requests
	)

	return {
		"status": overall,
		"signing_requests": requests,
		"can_sign": can_sign,
	}


@frappe.whitelist()
def get_form_actions(doctype, docname):
	"""Called by the global JS on form load.

	Returns whether the Sign button should appear, current status, etc.
	This is the entry point for Ranga's frontend JS.
	"""
	status_info = get_signing_status(doctype, docname)

	# Get agent port from settings
	settings = frappe.get_single("DSC Settings")

	return {
		**status_info,
		"agent_port": settings.agent_listen_port or 4645,
	}


@frappe.whitelist()
def retry(signing_request):
	"""Reset a Failed signing request back to Pending for retry."""
	from e_sign.digital_signature.audit import log_event

	doc = frappe.get_doc("DSC Signing Request", signing_request)

	if doc.status != "Failed":
		frappe.throw("Only failed requests can be retried.")

	doc.status = "Pending"
	doc.failure_reason = ""
	doc.save(ignore_permissions=True)

	if doc.source_doctype == "DSC Document Sign":
		frappe.db.set_value("DSC Document Sign", doc.source_name, "status", "Pending")

	log_event(signing_request, "Request Retried", {
		"previous_failure": doc.failure_reason,
	})

	return {"status": "Pending"}


@frappe.whitelist()
def cancel(signing_request, reason=""):
	"""Cancel a pending signing request."""
	from e_sign.digital_signature.audit import log_event

	doc = frappe.get_doc("DSC Signing Request", signing_request)

	if doc.status not in ("Pending", "Failed"):
		frappe.throw("Only pending or failed requests can be cancelled.")

	doc.status = "Cancelled"
	doc.cancelled_on = now_datetime()
	doc.save(ignore_permissions=True)

	if doc.source_doctype == "DSC Document Sign":
		frappe.db.set_value("DSC Document Sign", doc.source_name, "status", "Cancelled")

	log_event(signing_request, "Request Cancelled", {"reason": reason})

	_run_dev_hooks(
		"dsc_on_decline",
		signing_request=signing_request,
		reason=reason,
		doctype=doc.source_doctype,
		docname=doc.source_name,
	)

	return {"status": "Cancelled"}


@frappe.whitelist()
def abort_in_progress(signing_request, reason=""):
	"""Reset an In Progress request back to Pending after a client-side failure.

	Initiate flips the request to In Progress before handing off to the browser
	+ agent. If the agent call or finalize fails (network, PIN cancelled, agent
	crashed), the request is stuck and the user can't retry. Call this from the
	JS catch handler to free it.
	"""
	from e_sign.digital_signature.audit import log_event

	doc = frappe.get_doc("DSC Signing Request", signing_request)

	if doc.status != "In Progress":
		return {"status": doc.status}

	doc.status = "Pending"
	doc.failure_reason = (reason or "Client-side abort")[:140]
	doc.save(ignore_permissions=True)

	if doc.source_doctype == "DSC Document Sign":
		frappe.db.set_value("DSC Document Sign", doc.source_name, "status", "Pending")

	log_event(signing_request, "Request Aborted", {"reason": reason})

	return {"status": "Pending"}


def add_timeline_entry(doctype, docname, signing_request_name):
	"""Add a timeline comment to the source document."""
	req = frappe.get_doc("DSC Signing Request", signing_request_name)
	profile = frappe.get_doc("DSC Profile", req.profile)

	signer_name = profile.certificate_common_name or profile.label or profile.profile_name
	comment_text = (
		f"Digitally signed by <b>{signer_name}</b> "
		f"({profile.designation_for_stamp or profile.label or ''}) "
		f"at {req.signed_on}"
	)

	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": doctype,
			"reference_name": docname,
			"content": comment_text,
		}
	).insert(ignore_permissions=True)


def notify_admins_of_failure(signing_request_name, error_message):
	"""Email all DSC Administrators when a signing request fails (PRD §F8.3)."""
	admins = frappe.get_all(
		"Has Role",
		filters={"role": "DSC Administrator", "parenttype": "User"},
		fields=["parent"],
	)
	recipients = [a.parent for a in admins if a.parent and a.parent != "Administrator"]
	if not recipients:
		return

	req = frappe.db.get_value(
		"DSC Signing Request",
		signing_request_name,
		["source_doctype", "source_name", "profile", "rule"],
		as_dict=True,
	) or {}

	site_url = frappe.utils.get_url()
	frappe.sendmail(
		recipients=recipients,
		subject=f"DSC signing failed: {req.get('source_doctype', '')} {req.get('source_name', '')}",
		message=(
			f"<p>A DSC signing request has failed and needs investigation.</p>"
			f"<ul>"
			f"<li><b>Request:</b> {signing_request_name}</li>"
			f"<li><b>Document:</b> {req.get('source_doctype', '')} {req.get('source_name', '')}</li>"
			f"<li><b>Profile:</b> {req.get('profile', '')}</li>"
			f"<li><b>Rule:</b> {req.get('rule', '')}</li>"
			f"<li><b>Error:</b> <code>{frappe.utils.escape_html(error_message)[:500]}</code></li>"
			f"</ul>"
			f"<p><a href='{site_url}/app/dsc-signing-request/{signing_request_name}'>"
			f"Open request</a> · "
			f"<a href='{site_url}/app/dsc-audit-event?request={signing_request_name}'>"
			f"View audit trail</a></p>"
		),
		now=True,
	)


def send_signed_notification(doctype, docname, signing_request_name):
	"""Send notification to document creator that signing is complete."""
	doc = frappe.get_doc(doctype, docname)
	creator = doc.owner

	if creator == frappe.session.user:
		return  # No need to notify yourself

	req = frappe.get_doc("DSC Signing Request", signing_request_name)
	profile = frappe.get_doc("DSC Profile", req.profile)
	signer_name = profile.certificate_common_name or profile.label

	frappe.sendmail(
		recipients=[creator],
		subject=f"{doctype} {docname} has been digitally signed",
		message=(
			f"<p>{doctype} <b>{docname}</b> has been digitally signed by "
			f"<b>{signer_name}</b>.</p>"
			f"<p>The signed PDF is attached to the document.</p>"
		),
	)
