"""
Server API for DSC signing workflow.

These whitelisted endpoints are called by the browser JavaScript
to orchestrate the three-way signing flow:
  Browser → Server (initiate) → Browser → Agent (sign) → Browser → Server (finalize)
"""

import frappe
from frappe.utils import now_datetime, time_diff_in_seconds


@frappe.whitelist()
def initiate(doctype, docname):
	"""Start the signing process for a document.

	Called when the signer clicks "Sign with DSC".
	1. Validates permissions
	2. Finds the pending DSC Signing Request
	3. Calls signing_engine to prepare PDF and compute hash
	4. Returns session_id + hash for the browser to send to the agent

	Returns:
		dict: {session_id, hash_to_sign, hash_algorithm, expected_cert_fingerprint, visual_metadata}
	"""
	from e_sign.digital_signature.audit import log_event
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

	# Check certificate expiry
	if profile.certificate_not_after:
		from frappe.utils import getdate
		if getdate(profile.certificate_not_after) < getdate(now_datetime()):
			frappe.throw(
				f"Certificate for profile '{profile.profile_name}' expired on "
				f"{profile.certificate_not_after}. Please renew."
			)

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

	# Get print format from the rule
	print_format = None
	if signing_request.get("rule"):
		rule = frappe.get_doc("DSC Rule", signing_request.rule)
		print_format = rule.print_format

	if not print_format:
		# Use the DocType's default print format (field lives on DocType, not Print Format)
		print_format = frappe.db.get_value("DocType", doctype, "default_print_format")
		if not print_format:
			print_format = "Standard"

	# Update request status to In Progress
	frappe.db.set_value("DSC Signing Request", signing_request.name, {
		"status": "In Progress",
		"client_ip": getattr(frappe.local, "request_ip", None),
		"client_user_agent": (
			frappe.local.request.headers.get("User-Agent", "")
			if getattr(frappe.local, "request", None) else None
		),
	})

	# Prepare PDF and compute hash
	result = prepare_pdf_for_signing(
		doctype=doctype,
		docname=docname,
		print_format=print_format,
		sig_template=sig_template,
		profile=profile,
		signing_request_name=signing_request.name,
	)

	# Update request with hash
	frappe.db.set_value("DSC Signing Request", signing_request.name, {
		"hash_algorithm": result["hash_algorithm"],
		"hash_to_be_signed": result["hash_to_sign"],
	})

	# Log audit events
	log_event(signing_request.name, "Hash Computed", {
		"algorithm": result["hash_algorithm"],
		"hash_preview": result["hash_to_sign"][:16] + "...",
	})

	# Build response
	settings = frappe.get_single("DSC Settings")
	return {
		"session_id": result["session_id"],
		"hash_to_sign": result["hash_to_sign"],
		"hash_algorithm": result["hash_algorithm"],
		"expected_cert_fingerprint": profile.certificate_fingerprint,
		"signing_request": signing_request.name,
		"visual_metadata": {
			"signer_name": profile.certificate_common_name or profile.label,
			"reason": settings.default_reason or "Approved",
			"location": settings.default_location or "",
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

	# Log that we received the signature from the agent
	log_event(signing_request_name, "Signature Returned", {
		"cert_fingerprint": cert_der_b64[:32] + "..." if cert_der_b64 else None,
		"has_chain": bool(cert_chain_der_b64),
		"has_ocsp": bool(ocsp_der_b64),
	})

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

		# Update signing request
		frappe.db.set_value("DSC Signing Request", signing_request_name, {
			"status": "Signed",
			"actual_signer_user": frappe.session.user,
			"signed_on": now_datetime(),
			"sign_duration_seconds": duration,
			"signature_bytes": signature_bytes_b64[:200] + "...",  # truncate for storage
			"certificate_fingerprint_presented": signed_result.get("certificate_fingerprint"),
			"ocsp_response_b64": ocsp_der_b64[:200] + "..." if ocsp_der_b64 else None,
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

		frappe.db.commit()

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
		log_event(signing_request_name, "Request Failed", {
			"reason": str(e),
			"error_type": type(e).__name__,
		})
		frappe.db.commit()
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

	log_event(signing_request, "Request Cancelled", {"reason": reason})

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
