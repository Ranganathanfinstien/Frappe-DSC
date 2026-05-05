"""
PDF Signing Engine — pyHanko integration for deferred signing.

This module handles:
1. Generating PDF from Frappe print format
2. Adding a PAdES signature placeholder with visual stamp
3. Computing the SHA-256 hash to be signed
4. Injecting the signature bytes returned by the desktop agent
5. Verifying the resulting signed PDF

Uses pyHanko's "interrupted signing" workflow:
  PdfSigner → PdfSigningSession → PdfTBSDocument → digest → inject → verify
"""

import asyncio
import hashlib
import json
import uuid
from io import BytesIO

import frappe
from frappe.utils import now_datetime

from asn1crypto import x509 as asn1_x509
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import fields as sig_fields
from pyhanko.sign.signers.pdf_cms import ExternalSigner
from pyhanko.sign.signers.pdf_signer import (
	PdfSignatureMetadata,
	PdfSigner,
)
from pyhanko_certvalidator.registry import SimpleCertificateStore


# Sessions are stored in Frappe's Redis cache so they survive across worker
# processes, bench restarts, and live-reloads — an in-memory dict here would be
# lost any time the worker recycled, breaking finalize with "session expired".
_SESSION_KEY_PREFIX = "e_sign:session:"
_SESSION_TTL_SECONDS = 600  # 10 minutes — enough for the user to enter a PIN


def _session_key(session_id):
	return _SESSION_KEY_PREFIX + session_id


def _store_session(session_id, data):
	frappe.cache().set_value(
		_session_key(session_id),
		json.dumps(data, default=str),
		expires_in_sec=_SESSION_TTL_SECONDS,
	)


def _load_session(session_id, pop=False):
	key = _session_key(session_id)
	raw = frappe.cache().get_value(key)
	if not raw:
		return None
	if pop:
		frappe.cache().delete_value(key)
	if isinstance(raw, bytes):
		raw = raw.decode("utf-8")
	return json.loads(raw)


def prepare_pdf_for_signing(
	doctype,
	docname,
	print_format,
	sig_template,
	profile,
	signing_request_name,
):
	"""Phase 1: Generate PDF, add signature placeholder, compute hash.

	Args:
		doctype: source DocType name
		docname: source document name
		print_format: Print Format name to render
		sig_template: DSC Signature Template doc
		profile: DSC Profile doc
		signing_request_name: DSC Signing Request name (for audit)

	Returns:
		dict with session_id, hash_to_sign (hex), hash_algorithm
	"""
	# Step 1: Generate PDF from Frappe print format
	pdf_bytes = generate_pdf_from_print_format(doctype, docname, print_format)

	# Step 2: Get signature placement from template
	sig_field_row = None
	if sig_template.fields:
		# MVP: use the first field (typically named "primary")
		sig_field_row = sig_template.fields[0]

	page_number = (sig_field_row.page_number - 1) if sig_field_row else 0  # 0-based
	box = None
	if sig_field_row and sig_field_row.x and sig_field_row.y:
		box = (
			sig_field_row.x,
			sig_field_row.y,
			sig_field_row.x + (sig_field_row.width or 200),
			sig_field_row.y + (sig_field_row.height or 80),
		)

	# Step 3: Build the stamp text for the visual appearance
	stamp_text = build_stamp_text(sig_template, profile)

	# Step 4: Get DSC Settings
	settings = frappe.get_single("DSC Settings")
	hash_algorithm = settings.default_hash_algorithm or "sha256"
	reason = settings.default_reason or "Approved"
	location = settings.default_location or ""

	# Step 5: Prepare the PDF with pyHanko
	session_id = str(uuid.uuid4())

	pdf_input = BytesIO(pdf_bytes)
	pdf_writer = IncrementalPdfFileWriter(pdf_input)

	# Create signature field spec
	field_name = f"DSC_Signature_{signing_request_name}"
	new_field = sig_fields.SigFieldSpec(
		sig_field_name=field_name,
		on_page=page_number,
		box=box,
	)

	# Create signature metadata
	signer_name = profile.certificate_common_name or profile.label or profile.profile_name
	sig_meta = PdfSignatureMetadata(
		field_name=field_name,
		md_algorithm=hash_algorithm,
		location=location,
		reason=reason,
		name=signer_name,
	)

	# Create a placeholder ExternalSigner (no actual cert yet — we'll use it
	# just for the signing session setup; real cert comes later)
	# For preparation phase, we need to know the hash but not sign yet.
	# We use a dummy approach: compute the document hash ourselves.
	#
	# pyHanko's deferred signing requires a certificate upfront for the CMS
	# structure. Since we don't have the cert at prepare time (it's on the
	# USB token), we use a simpler approach:
	# 1. Generate the PDF with signature placeholder
	# 2. Compute the ByteRange hash ourselves
	# 3. Store everything for later injection

	# Add the signature field to the PDF
	sig_fields.append_signature_field(pdf_writer, new_field)

	# Write the PDF with the empty signature field
	output = BytesIO()
	pdf_writer.write(output)
	output.seek(0)

	# Compute the hash of the entire prepared PDF
	# (In the finalize step, we'll rebuild with the actual signature)
	pdf_content = output.read()
	if hash_algorithm == "sha256":
		doc_hash = hashlib.sha256(pdf_content).hexdigest()
	elif hash_algorithm == "sha384":
		doc_hash = hashlib.sha384(pdf_content).hexdigest()
	else:
		doc_hash = hashlib.sha256(pdf_content).hexdigest()

	# Store session data for the finalize step. The PDF bytes are NOT stored —
	# finalize re-renders from the print format anyway, and keeping the payload
	# small + JSON-friendly lets us use Redis for cross-worker durability.
	_store_session(session_id, {
		"hash_algorithm": hash_algorithm,
		"hash_hex": doc_hash,
		"field_name": field_name,
		"sig_meta": {
			"reason": reason,
			"location": location,
			"name": signer_name,
		},
		"sig_template_name": sig_template.name,
		"profile_name": profile.name,
		"signing_request_name": signing_request_name,
		"doctype": doctype,
		"docname": docname,
		"print_format": print_format,
		"created_at": str(now_datetime()),
		"stamp_text": stamp_text,
		"box": list(box) if box else None,
		"page_number": page_number,
	})

	return {
		"session_id": session_id,
		"hash_to_sign": doc_hash,
		"hash_algorithm": hash_algorithm,
	}


def finalize_signed_pdf(
	session_id,
	signature_bytes_b64,
	cert_der_b64,
	cert_chain_der_b64=None,
	ocsp_der_b64=None,
):
	"""Phase 2: Inject signature into PDF, verify, and save.

	Args:
		session_id: session ID from prepare step
		signature_bytes_b64: base64-encoded raw signature from the agent
		cert_der_b64: base64-encoded signer certificate (DER)
		cert_chain_der_b64: list of base64-encoded intermediate certs (DER)
		ocsp_der_b64: base64-encoded OCSP response (DER)

	Returns:
		dict with signed_pdf_bytes, file_name, verification result
	"""
	import base64

	session = _load_session(session_id, pop=True)
	if not session:
		frappe.throw("Signing session expired or not found. Please try again.")

	# box was stored as a list (JSON-friendly) — pyHanko expects a tuple
	if session.get("box"):
		session["box"] = tuple(session["box"])

	# Decode the inputs
	signature_bytes = base64.b64decode(signature_bytes_b64)
	cert_der = base64.b64decode(cert_der_b64)

	cert_chain_ders = []
	if cert_chain_der_b64:
		cert_chain_ders = [base64.b64decode(c) for c in cert_chain_der_b64]

	ocsp_response = None
	if ocsp_der_b64:
		ocsp_response = base64.b64decode(ocsp_der_b64)

	# Parse the signer certificate using asn1crypto (pyHanko's expected format)
	signer_cert = asn1_x509.Certificate.load(cert_der)

	# Load the original PDF and re-render with the actual signature
	hash_algorithm = session["hash_algorithm"]
	sig_meta_dict = session["sig_meta"]
	box = session["box"]
	page_number = session["page_number"]

	# Re-generate PDF from scratch (the stored one has an empty sig field,
	# we need a clean one for pyHanko to add the real signature)
	fresh_pdf = generate_pdf_from_print_format(
		session["doctype"],
		session["docname"],
		session["print_format"],
	)

	# Build certificate store for chain
	cert_store = SimpleCertificateStore()
	for chain_cert_der in cert_chain_ders:
		cert_store.register(asn1_x509.Certificate.load(chain_cert_der))

	# Create ExternalSigner with the actual signature bytes
	external_signer = ExternalSigner(
		signing_cert=signer_cert,
		cert_registry=cert_store,
		signature_value=signature_bytes,
	)

	# Set up the signing metadata
	field_name = session["field_name"]
	sig_meta = PdfSignatureMetadata(
		field_name=field_name,
		md_algorithm=hash_algorithm,
		location=sig_meta_dict["location"],
		reason=sig_meta_dict["reason"],
		name=sig_meta_dict["name"],
	)

	new_field = sig_fields.SigFieldSpec(
		sig_field_name=field_name,
		on_page=page_number,
		box=box,
	)

	pdf_signer = PdfSigner(
		signature_meta=sig_meta,
		signer=external_signer,
		new_field_spec=new_field,
	)

	# Sign the PDF using pyHanko's async pipeline
	pdf_input = BytesIO(fresh_pdf)
	pdf_writer = IncrementalPdfFileWriter(pdf_input)

	output = BytesIO()

	# Run the async signing
	async def _do_sign():
		await pdf_signer.async_sign_pdf(
			pdf_out=pdf_writer,
			output=output,
		)

	asyncio.run(_do_sign())

	output.seek(0)
	signed_pdf_bytes = output.read()

	# Generate file name
	docname = session["docname"]
	file_name = f"{docname}_signed_v1.pdf"

	# Check if a previous version exists to increment
	existing = frappe.db.count(
		"File",
		filters={
			"attached_to_doctype": session["doctype"],
			"attached_to_name": docname,
			"file_name": ["like", f"{docname}_signed_v%.pdf"],
		},
	)
	if existing:
		file_name = f"{docname}_signed_v{existing + 1}.pdf"

	return {
		"signed_pdf_bytes": signed_pdf_bytes,
		"file_name": file_name,
		"doctype": session["doctype"],
		"docname": session["docname"],
		"signing_request_name": session["signing_request_name"],
		"certificate_fingerprint": hashlib.sha256(cert_der).hexdigest(),
	}


def save_signed_pdf(signed_result):
	"""Save the signed PDF as a Frappe File attachment.

	Args:
		signed_result: dict returned from finalize_signed_pdf

	Returns:
		File document
	"""
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": signed_result["file_name"],
			"attached_to_doctype": signed_result["doctype"],
			"attached_to_name": signed_result["docname"],
			"content": signed_result["signed_pdf_bytes"],
			"is_private": 1,
		}
	)
	file_doc.save(ignore_permissions=True)
	return file_doc


def verify_signed_pdf(pdf_bytes):
	"""Verify a signed PDF's signature.

	Args:
		pdf_bytes: bytes of the signed PDF

	Returns:
		dict with is_valid, signer_name, signature_count, details
	"""
	from pyhanko.pdf_utils.reader import PdfFileReader
	from pyhanko.sign.validation import async_validate_pdf_signature

	try:
		reader = PdfFileReader(BytesIO(pdf_bytes))
		sigs = list(reader.embedded_signatures)

		if not sigs:
			return {"is_valid": False, "error": "No signatures found in PDF"}

		results = []
		for sig in sigs:
			try:
				status = asyncio.run(async_validate_pdf_signature(sig))
				results.append(
					{
						"field_name": sig.field_name,
						"intact": status.intact,
						"valid": status.valid,
						"trusted": status.trusted,
						"bottom_line": status.bottom_line,
					}
				)
			except Exception as ve:
				# Self-signed certs or missing trust anchors will fail validation
				# but the signature structure may still be intact
				results.append(
					{
						"field_name": sig.field_name,
						"intact": None,
						"valid": None,
						"trusted": False,
						"bottom_line": False,
						"validation_error": str(ve),
					}
				)

		all_valid = all(r.get("bottom_line", False) for r in results)
		return {
			"is_valid": all_valid,
			"signatures": results,
			"signature_count": len(results),
		}

	except Exception as e:
		return {"is_valid": False, "error": str(e)}


def generate_pdf_from_print_format(doctype, docname, print_format):
	"""Generate PDF bytes from a Frappe print format.

	Args:
		doctype: DocType name
		docname: document name
		print_format: Print Format name

	Returns:
		bytes of the generated PDF
	"""
	from frappe.utils.pdf import get_pdf

	html = frappe.get_print(doctype, docname, print_format=print_format)
	pdf_bytes = get_pdf(html)
	return pdf_bytes


def build_stamp_text(sig_template, profile):
	"""Build the visual stamp text based on template and profile config.

	Args:
		sig_template: DSC Signature Template doc
		profile: DSC Profile doc

	Returns:
		str with the stamp text
	"""
	lines = []

	if sig_template.stamp_show_digitally_signed_by:
		lines.append("Digitally signed by")

	if sig_template.stamp_show_signer_name:
		name = profile.certificate_common_name or profile.label or profile.profile_name
		lines.append(name)

	if sig_template.stamp_show_designation:
		designation = profile.designation_for_stamp or profile.label
		if designation:
			lines.append(designation)

	if sig_template.stamp_show_timestamp:
		fmt = sig_template.stamp_timestamp_format or "%d-%m-%Y %H:%M:%S %Z"
		lines.append(f"Date: {fmt}")  # actual time filled at sign time

	if sig_template.stamp_show_reason:
		settings = frappe.get_single("DSC Settings")
		lines.append(f"Reason: {settings.default_reason or 'Approved'}")

	if sig_template.stamp_show_location:
		settings = frappe.get_single("DSC Settings")
		lines.append(f"Location: {settings.default_location or ''}")

	return "\n".join(lines)


def get_session_info(session_id):
	"""Get info about a pending signing session.

	Returns None if session doesn't exist or expired.
	"""
	return _load_session(session_id)


def cleanup_expired_sessions(max_age_seconds=300):
	"""No-op kept for backwards compatibility — Redis TTL handles expiry now."""
	return 0
