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
import base64
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from io import BytesIO

import frappe
from frappe.utils import now_datetime

from asn1crypto import algos, cms, core, x509 as asn1_x509
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import fields as sig_fields
from pyhanko.sign.signers.pdf_byterange import PreparedByteRangeDigest
from pyhanko.sign.signers.pdf_cms import ExternalSigner
from pyhanko.sign.signers.pdf_signer import (
	PdfSignatureMetadata,
	PdfSigner,
	PdfTBSDocument,
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
	cert_der,
	signer_location_text=None,
	pdf_bytes=None,
	placement=None,
):
	"""Phase 1: build a PAdES-compliant PDF, return the SignedAttrs hash for the token.

	Implements the proper deferred external signing flow:
	1. pyHanko places the signature dictionary with a fixed-size placeholder
	2. pyHanko computes the ByteRange digest (sha256 of bytes excluding placeholder)
	3. We build CMS SignedAttrs manually with that digest as `message-digest`
	4. The token signs sha256(SignedAttrs DER) — that goes into SignerInfo.signature
	5. finalize_signed_pdf injects the complete CMS into the placeholder

	cert_der is the signer's certificate from the token — required because
	SignedAttrs references the signer-certificate via `signing-certificate-v2`
	and Adobe's verifier checks that the cert chain in the CMS matches.

	pdf_bytes / placement support ad-hoc uploaded-document signing (DSC Document
	Sign): when pdf_bytes is given, that PDF is signed as-is instead of being
	rendered from a print format, and placement — a dict of
	{page, x, y, width, height} in PDF points — positions the signature box
	instead of the saved signature template field.

	Returns:
		dict with session_id, hash_to_sign (hex of SignedAttrs hash), hash_algorithm, expected_cert_fingerprint
	"""
	if pdf_bytes is None:
		pdf_bytes = generate_pdf_from_print_format(doctype, docname, print_format)

	if placement:
		# Interactive placement (uploaded document) — coordinates already in
		# PDF points with origin at the bottom-left, exactly what pyHanko wants.
		page_number = max(int(placement.get("page") or 1) - 1, 0)
		px = placement.get("x") or 0
		py = placement.get("y") or 0
		box = (
			px,
			py,
			px + (placement.get("width") or 200),
			py + (placement.get("height") or 80),
		)
	else:
		sig_field_row = None
		if sig_template.fields:
			sig_field_row = sig_template.fields[0]

		page_number = (sig_field_row.page_number - 1) if sig_field_row else 0
		box = None
		if sig_field_row and sig_field_row.x and sig_field_row.y:
			box = (
				sig_field_row.x,
				sig_field_row.y,
				sig_field_row.x + (sig_field_row.width or 200),
				sig_field_row.y + (sig_field_row.height or 80),
			)

	settings = frappe.get_single("DSC Settings")
	hash_algorithm = settings.default_hash_algorithm or "sha256"
	reason = settings.default_reason or "Approved"
	location = signer_location_text or settings.default_location or ""
	signer_name = profile.certificate_common_name or profile.label or profile.profile_name
	stamp_text = build_stamp_text(sig_template, profile, signer_location_text=location)

	session_id = str(uuid.uuid4())
	signer_cert = asn1_x509.Certificate.load(cert_der)

	field_name = f"DSC_Signature_{signing_request_name}"
	new_field = sig_fields.SigFieldSpec(
		sig_field_name=field_name,
		on_page=page_number,
		box=box,
	)
	sig_meta = PdfSignatureMetadata(
		field_name=field_name,
		md_algorithm=hash_algorithm,
		location=location,
		reason=reason,
		name=signer_name,
	)

	# ExternalSigner needs *some* signature_value at construction time — pyHanko
	# only uses it during async_sign which we don't call here. The deferred
	# helper (async_digest_doc_for_signing) only needs the cert to size the
	# placeholder. We pass a max-size zeroed value; the real signature replaces
	# it via PdfTBSDocument.finish_signing in phase 2.
	placeholder_signer = ExternalSigner(
		signing_cert=signer_cert,
		cert_registry=SimpleCertificateStore(),
		signature_value=b"\x00" * 512,
	)

	pdf_input = BytesIO(pdf_bytes)
	pdf_writer = IncrementalPdfFileWriter(pdf_input)
	pdf_signer = PdfSigner(
		signature_meta=sig_meta,
		signer=placeholder_signer,
		new_field_spec=new_field,
	)

	output = BytesIO()

	async def _prepare():
		# Reserve enough room for the full CMS — Indian DSCs have a 3-cert
		# chain (signer → CA → CCA root) plus OCSP, which pushes the CMS
		# past pyHanko's default 8 KB estimate. 32 KB gives comfortable
		# headroom without bloating the PDF.
		return await pdf_signer.async_digest_doc_for_signing(
			pdf_out=pdf_writer,
			output=output,
			bytes_reserved=32768,
		)

	prep_digest, _tbs_doc, _ = asyncio.run(_prepare())

	# Capture the prepared PDF bytes (with placeholder) — these are what
	# finalize will inject the CMS into. We must preserve byte-for-byte.
	output.seek(0)
	prepared_pdf_bytes = output.read()

	# Build CMS SignedAttrs manually. The token signs sha256 of this DER.
	signing_time = datetime.now(timezone.utc).replace(microsecond=0)
	signed_attrs = cms.CMSAttributes([
		cms.CMSAttribute({
			"type": "content_type",
			"values": [cms.ContentType("data")],
		}),
		cms.CMSAttribute({
			"type": "signing_time",
			"values": [cms.Time({"utc_time": signing_time})],
		}),
		cms.CMSAttribute({
			"type": "message_digest",
			"values": [core.OctetString(prep_digest.document_digest)],
		}),
	])
	signed_attrs_der = signed_attrs.dump()
	hash_to_sign_hex = hashlib.sha256(signed_attrs_der).hexdigest()

	_store_session(session_id, {
		"hash_algorithm": hash_algorithm,
		"field_name": field_name,
		"signing_request_name": signing_request_name,
		"doctype": doctype,
		"docname": docname,
		"print_format": print_format,
		"created_at": str(now_datetime()),
		"prepared_pdf_b64": base64.b64encode(prepared_pdf_bytes).decode("ascii"),
		"signed_attrs_b64": base64.b64encode(signed_attrs_der).decode("ascii"),
		"cert_der_b64": base64.b64encode(cert_der).decode("ascii"),
		"prep_digest": {
			"document_digest_hex": prep_digest.document_digest.hex(),
			"reserved_region_start": prep_digest.reserved_region_start,
			"reserved_region_end": prep_digest.reserved_region_end,
		},
	})

	cert_fingerprint = hashlib.sha256(cert_der).hexdigest()

	return {
		"session_id": session_id,
		"hash_to_sign": hash_to_sign_hex,
		"hash_algorithm": hash_algorithm,
		"expected_cert_fingerprint": cert_fingerprint,
	}


def finalize_signed_pdf(
	session_id,
	signature_bytes_b64,
	cert_der_b64,
	cert_chain_der_b64=None,
	ocsp_der_b64=None,
):
	"""Phase 2: Build CMS from the token signature, inject into the prepared placeholder.

	The prepared PDF (with placeholder) and the SignedAttrs we hashed in
	prepare are both stored in the session. We:
	1. Construct the full CMS ContentInfo with the token's signature value
	2. Use PreparedByteRangeDigest.fill_with_cms to drop those bytes into the
	   reserved region without touching the rest of the PDF.

	The result is a PAdES-compliant PDF where Adobe's verifier hashes the
	exact bytes the token signed.

	Args:
		session_id: session ID from prepare step
		signature_bytes_b64: base64-encoded raw signature from the agent
		cert_der_b64: base64-encoded signer certificate (from the bridge —
			should match the cert stored at prepare time)
		cert_chain_der_b64: list of base64-encoded intermediate certs (DER)
		ocsp_der_b64: base64-encoded OCSP response (DER) — currently unused
	"""
	session = _load_session(session_id, pop=True)
	if not session:
		frappe.throw("Signing session expired or not found. Please try again.")

	signature_bytes = base64.b64decode(signature_bytes_b64)

	# Prefer the cert from session (matches what we built SignedAttrs against).
	# The bridge re-sends it on /sign for redundancy, but if there's any
	# mismatch we must trust the prepare-time cert.
	cert_der = base64.b64decode(session["cert_der_b64"])
	signer_cert = asn1_x509.Certificate.load(cert_der)

	chain_certs = []
	if cert_chain_der_b64:
		for c in cert_chain_der_b64:
			chain_certs.append(asn1_x509.Certificate.load(base64.b64decode(c)))

	signed_attrs_der = base64.b64decode(session["signed_attrs_b64"])
	signed_attrs = cms.CMSAttributes.load(signed_attrs_der)

	signer_info = cms.SignerInfo({
		"version": "v1",
		"sid": cms.SignerIdentifier({
			"issuer_and_serial_number": cms.IssuerAndSerialNumber({
				"issuer": signer_cert.issuer,
				"serial_number": signer_cert.serial_number,
			}),
		}),
		"digest_algorithm": algos.DigestAlgorithm({"algorithm": "sha256"}),
		"signed_attrs": signed_attrs,
		"signature_algorithm": algos.SignedDigestAlgorithm({"algorithm": "rsassa_pkcs1v15"}),
		"signature": signature_bytes,
	})

	cert_choices = [cms.CertificateChoices({"certificate": signer_cert})]
	for c in chain_certs:
		cert_choices.append(cms.CertificateChoices({"certificate": c}))

	signed_data = cms.SignedData({
		"version": "v1",
		"digest_algorithms": cms.DigestAlgorithms([
			algos.DigestAlgorithm({"algorithm": "sha256"})
		]),
		"encap_content_info": cms.ContentInfo({
			"content_type": "data",
		}),
		"certificates": cms.CertificateSet(cert_choices),
		"signer_infos": cms.SignerInfos([signer_info]),
	})

	cms_content = cms.ContentInfo({
		"content_type": "signed_data",
		"content": signed_data,
	})
	cms_bytes = cms_content.dump()

	prepared_pdf_bytes = base64.b64decode(session["prepared_pdf_b64"])
	prep = session["prep_digest"]
	prep_digest_obj = PreparedByteRangeDigest(
		document_digest=bytes.fromhex(prep["document_digest_hex"]),
		reserved_region_start=prep["reserved_region_start"],
		reserved_region_end=prep["reserved_region_end"],
	)

	output = BytesIO(prepared_pdf_bytes)
	prep_digest_obj.fill_with_cms(output, cms_bytes)
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

	Tags the File with `is_dsc_signed=1` (custom field added by after_install)
	so the protection hook can refuse deletion by non-DSC-Administrators.

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

	# Flag if the custom field exists (it should, after install runs)
	if frappe.get_meta("File").get_field("is_dsc_signed"):
		frappe.db.set_value("File", file_doc.name, "is_dsc_signed", 1)

	return file_doc


# PEM bundle of every CCA India licensed CA, shipped with the app so signature
# verification trusts all Indian DSC tokens out of the box — no admin setup.
_BUILTIN_TRUST_BUNDLE = os.path.join(
	os.path.dirname(__file__), "cca_india_trust_bundle.pem"
)


def _parse_pem_certs(pem_bytes):
	"""Parse a PEM bundle's bytes into a list of x509 Certificate objects."""
	from asn1crypto import pem
	from asn1crypto.x509 import Certificate

	if isinstance(pem_bytes, str):
		pem_bytes = pem_bytes.encode()
	return [
		Certificate.load(der)
		for _, _, der in pem.unarmor(pem_bytes, multiple=True)
	]


def _load_trust_store():
	"""Build a pyhanko ValidationContext for signature verification.

	Trust roots = the CCA India bundle shipped with the app, plus any extra CA
	bundle an admin uploads in DSC Settings. The built-in bundle means every
	Indian DSC token verifies as trusted with zero setup; the uploaded bundle
	is additive, for trusting extra CAs (e.g. a private/internal CA).

	Returns ValidationContext or None. None falls back to pyhanko defaults so
	verification never breaks if neither source yields any certificates.
	"""
	try:
		from pyhanko_certvalidator import ValidationContext

		anchors = []

		if os.path.exists(_BUILTIN_TRUST_BUNDLE):
			# nosemgrep: frappe-security-file-traversal -- hardcoded path inside the app
			# directory (see _BUILTIN_TRUST_BUNDLE above); no user-controlled input.
			with open(_BUILTIN_TRUST_BUNDLE, "rb") as fh:
				anchors.extend(_parse_pem_certs(fh.read()))

		bundle_url = frappe.db.get_single_value("DSC Settings", "trust_store_bundle")
		if bundle_url:
			file_doc = frappe.get_doc("File", {"file_url": bundle_url})
			anchors.extend(_parse_pem_certs(file_doc.get_content()))

		if not anchors:
			return None

		return ValidationContext(trust_roots=anchors, allow_fetching=False)
	except Exception:
		frappe.log_error(title="DSC trust store load failed")
		return None


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

		validation_context = _load_trust_store()

		results = []
		for sig in sigs:
			try:
				status = asyncio.run(
					async_validate_pdf_signature(
						sig, signer_validation_context=validation_context
					)
				)
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
			"trust_store_configured": validation_context is not None,
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


def build_stamp_text(sig_template, profile, signer_location_text=None):
	"""Build the visual stamp text based on template and profile config.

	Args:
		sig_template: DSC Signature Template doc
		profile: DSC Profile doc
		signer_location_text: optional per-signer address to use for the
			"Location:" line. Falls back to DSC Settings.default_location.

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
		if signer_location_text:
			location = signer_location_text
		else:
			settings = frappe.get_single("DSC Settings")
			location = settings.default_location or ""
		lines.append(f"Location: {location}")

	return "\n".join(lines)


def get_session_info(session_id):
	"""Get info about a pending signing session.

	Returns None if session doesn't exist or expired.
	"""
	return _load_session(session_id)


def cleanup_expired_sessions(max_age_seconds=300):
	"""No-op kept for backwards compatibility — Redis TTL handles expiry now."""
	return 0
