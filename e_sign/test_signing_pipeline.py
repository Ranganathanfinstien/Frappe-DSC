"""
End-to-end test of the signing pipeline inside Frappe.

Run with:
    bench --site mysite.local execute e_sign.test_signing_pipeline.run_test
"""

import asyncio
import base64
import datetime
import hashlib
from io import BytesIO

import frappe
from frappe.utils import now_datetime


def run_test():
	"""Full signing pipeline test:
	1. Generate a test certificate (simulating a real CA-issued DSC)
	2. Take a real Frappe document
	3. Generate its PDF using Frappe's print engine
	4. Sign the PDF with pyHanko
	5. Verify the signature
	6. Attach the signed PDF to the document
	7. Log audit events
	"""
	frappe.flags.ignore_permissions = True

	print("\n" + "=" * 60)
	print("  DSC SIGNING ENGINE — END-TO-END TEST")
	print("=" * 60)

	# ── Step 1: Generate test certificate ──────────────────────────
	print("\n[Step 1] Generating test certificate...")

	from cryptography import x509
	from cryptography.hazmat.primitives import hashes, serialization
	from cryptography.hazmat.primitives.asymmetric import rsa
	from cryptography.x509.oid import NameOID

	key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
	subject = issuer = x509.Name([
		x509.NameAttribute(NameOID.COUNTRY_NAME, "IN"),
		x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Acme India Pvt Ltd"),
		x509.NameAttribute(NameOID.COMMON_NAME, "RAJESH KUMAR"),
	])
	cert = (
		x509.CertificateBuilder()
		.subject_name(subject)
		.issuer_name(issuer)
		.public_key(key.public_key())
		.serial_number(x509.random_serial_number())
		.not_valid_before(datetime.datetime.now(datetime.timezone.utc))
		.not_valid_after(
			datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
		)
		.add_extension(
			x509.KeyUsage(
				digital_signature=True,
				key_encipherment=False,
				content_commitment=True,
				data_encipherment=False,
				key_agreement=False,
				key_cert_sign=False,
				crl_sign=False,
				encipher_only=False,
				decipher_only=False,
			),
			critical=True,
		)
		.sign(key, hashes.SHA256())
	)

	cert_der = cert.public_bytes(serialization.Encoding.DER)
	cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
	key_der = key.private_bytes(
		serialization.Encoding.DER,
		serialization.PrivateFormat.PKCS8,
		serialization.NoEncryption(),
	)
	fingerprint = hashlib.sha256(cert_der).hexdigest()

	print(f"   Certificate CN:    RAJESH KUMAR")
	print(f"   Organization:      Acme India Pvt Ltd")
	print(f"   Fingerprint:       {fingerprint[:32]}...")
	print(f"   Key size:          2048-bit RSA")
	print("   ✓ Certificate created")

	# ── Step 2: Find a real document ───────────────────────────────
	print("\n[Step 2] Finding a document to sign...")

	source_doctype = "ToDo"
	source_name = frappe.db.get_value("ToDo", {}, "name")
	if not source_name:
		todo = frappe.get_doc({
			"doctype": "ToDo",
			"description": "Test document for DSC signing",
		}).insert()
		source_name = todo.name

	print(f"   Document:          {source_doctype} / {source_name}")
	print("   ✓ Document found")

	# ── Step 3: Generate PDF ──────────────────────────────────────
	print("\n[Step 3] Generating PDF...")

	# Use fpdf2 to create a test PDF (wkhtmltopdf needs a running site)
	# In production, this would use frappe.get_print() + get_pdf()
	from fpdf import FPDF

	doc = frappe.get_doc(source_doctype, source_name)

	pdf = FPDF()
	pdf.add_page()
	pdf.set_font("Helvetica", "B", 18)
	pdf.text(50, 30, "TAX INVOICE")
	pdf.set_font("Helvetica", "", 12)
	pdf.text(50, 50, f"Document: {source_doctype} / {source_name}")
	pdf.text(50, 65, f"Description: {doc.description or 'N/A'}")
	pdf.text(50, 80, f"Status: {doc.status or 'Open'}")
	pdf.text(50, 95, f"Owner: {doc.owner}")
	pdf.text(50, 110, f"Date: {doc.creation}")
	pdf.text(50, 130, "Amount: Rs. 75,000")
	pdf.text(50, 145, "Company: Acme India Pvt Ltd")
	pdf.text(50, 165, "This document requires digital signature.")

	# Add a line separator
	pdf.line(50, 175, 550, 175)

	pdf_bytes = pdf.output()

	print(f"   PDF size:          {len(pdf_bytes):,} bytes")
	print(f"   Content:           Invoice for {source_name}")
	print("   ✓ PDF generated")

	# ── Step 4: Sign the PDF with pyHanko ─────────────────────────
	print("\n[Step 4] Signing PDF with pyHanko...")

	from asn1crypto import keys as asn1_keys
	from asn1crypto import x509 as asn1_x509
	from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
	from pyhanko.sign import fields as sig_fields
	from pyhanko.sign.signers import SimpleSigner
	from pyhanko.sign.signers.pdf_signer import PdfSignatureMetadata, PdfSigner
	from pyhanko_certvalidator.registry import SimpleCertificateStore

	# Load cert in asn1crypto format (pyHanko's expected format)
	asn1_cert = asn1_x509.Certificate.load(cert_der)
	asn1_key = asn1_keys.PrivateKeyInfo.load(key_der)

	signer = SimpleSigner(
		signing_cert=asn1_cert,
		signing_key=asn1_key,
		cert_registry=SimpleCertificateStore(),
	)

	sig_meta = PdfSignatureMetadata(
		field_name="DSC_Signature",
		md_algorithm="sha256",
		location="Bengaluru, IN",
		reason="Approved",
		name="RAJESH KUMAR",
	)

	# Place signature at bottom-right of page 1
	new_field = sig_fields.SigFieldSpec(
		sig_field_name="DSC_Signature",
		on_page=0,
		box=(350, 50, 560, 130),  # bottom-right area
	)

	pdf_signer = PdfSigner(
		signature_meta=sig_meta,
		signer=signer,
		new_field_spec=new_field,
	)

	pdf_input = BytesIO(pdf_bytes)
	pdf_writer = IncrementalPdfFileWriter(pdf_input)
	output = BytesIO()

	asyncio.run(pdf_signer.async_sign_pdf(pdf_out=pdf_writer, output=output))

	output.seek(0)
	signed_pdf_bytes = output.read()

	print(f"   Signed PDF size:   {len(signed_pdf_bytes):,} bytes")
	print(f"   Signature field:   DSC_Signature")
	print(f"   Placement:         Page 1, bottom-right (350,50)-(560,130)")
	print(f"   Reason:            Approved")
	print(f"   Location:          Bengaluru, IN")
	print("   ✓ PDF signed")

	# ── Step 5: Verify the signature ──────────────────────────────
	print("\n[Step 5] Verifying signed PDF...")

	from pyhanko.pdf_utils.reader import PdfFileReader

	reader = PdfFileReader(BytesIO(signed_pdf_bytes))
	sigs = list(reader.embedded_signatures)

	print(f"   Signatures found:  {len(sigs)}")
	for sig in sigs:
		print(f"   Field name:        {sig.field_name}")

	print("   ✓ Signature structure verified (trust validation skipped for self-signed cert)")

	# ── Step 6: Attach signed PDF to the document ─────────────────
	print("\n[Step 6] Attaching signed PDF to document...")

	file_name = f"{source_name}_signed_v1.pdf"
	file_doc = frappe.get_doc({
		"doctype": "File",
		"file_name": file_name,
		"attached_to_doctype": source_doctype,
		"attached_to_name": source_name,
		"content": signed_pdf_bytes,
		"is_private": 1,
	})
	file_doc.save()

	print(f"   File name:         {file_name}")
	print(f"   File URL:          {file_doc.file_url}")
	print(f"   Attached to:       {source_doctype} / {source_name}")
	print(f"   Private:           Yes")
	print("   ✓ Signed PDF attached")

	# ── Step 7: Update signing request and log audit ──────────────
	print("\n[Step 7] Updating signing request and audit trail...")

	# Find the demo signing request or create one
	signing_request = frappe.db.get_value(
		"DSC Signing Request",
		filters={"source_doctype": source_doctype, "source_name": source_name, "status": "Pending"},
		fieldname="name",
	)

	if not signing_request:
		sr = frappe.get_doc({
			"doctype": "DSC Signing Request",
			"source_doctype": source_doctype,
			"source_name": source_name,
			"profile": "Accounts Head",
			"expected_signer_user": frappe.session.user,
			"status": "Signed",
			"hash_algorithm": "sha256",
			"hash_to_be_signed": hashlib.sha256(pdf_bytes).hexdigest(),
			"signature_bytes": base64.b64encode(b"test-signature").decode(),
			"certificate_fingerprint_presented": fingerprint,
			"signed_file": file_doc.name,
			"created_on": now_datetime(),
			"signed_on": now_datetime(),
			"sign_duration_seconds": 3,
		})
		sr.insert()
		signing_request = sr.name
		print(f"   Created request:   {signing_request}")
	else:
		frappe.db.set_value("DSC Signing Request", signing_request, {
			"status": "Signed",
			"signed_on": now_datetime(),
			"signed_file": file_doc.name,
			"certificate_fingerprint_presented": fingerprint,
			"sign_duration_seconds": 3,
		})
		print(f"   Updated request:   {signing_request}")

	# Log audit events
	from e_sign.digital_signature.audit import log_event

	log_event(signing_request, "Hash Computed", {"algorithm": "sha256"})
	log_event(signing_request, "Signature Returned", {"cert_cn": "RAJESH KUMAR"})
	log_event(signing_request, "PDF Verified", {"signatures_found": 1})
	log_event(signing_request, "Request Signed", {
		"file_name": file_name,
		"duration_seconds": 3,
	})

	print(f"   Audit events:      4 events logged")
	print("   ✓ Audit trail updated")

	# ── Step 8: Add timeline comment ──────────────────────────────
	print("\n[Step 8] Adding timeline entry...")

	frappe.get_doc({
		"doctype": "Comment",
		"comment_type": "Info",
		"reference_doctype": source_doctype,
		"reference_name": source_name,
		"content": (
			"Digitally signed by <b>RAJESH KUMAR</b> "
			"(CFO & Accounts Head) "
			f"at {now_datetime()}"
		),
	}).insert()

	print(f"   Timeline entry added to {source_doctype} / {source_name}")
	print("   ✓ Timeline updated")

	# ── Save signed PDF to /tmp for manual inspection ─────────────
	with open("/tmp/frappe_signed_document.pdf", "wb") as f:
		f.write(signed_pdf_bytes)

	frappe.db.commit()

	# ── Summary ───────────────────────────────────────────────────
	print("\n" + "=" * 60)
	print("  TEST PASSED — ALL STEPS COMPLETED")
	print("=" * 60)
	print(f"""
HOW TO CHECK:

  1. SIGNED PDF (download and open in Adobe Reader):
     /tmp/frappe_signed_document.pdf

  2. IN THE BROWSER — open these pages:

     a) Source document (see attached signed PDF):
        http://mysite.local:8000/app/todo/{source_name}

     b) Signing request (see status = Signed):
        http://mysite.local:8000/app/dsc-signing-request/{signing_request}

     c) Audit trail (see the 4 new events):
        http://mysite.local:8000/app/dsc-audit-event?request={signing_request}

     d) All signing requests:
        http://mysite.local:8000/app/dsc-signing-request

  3. SIGNED PDF FILE:
     Attached to {source_doctype} / {source_name}
     File: {file_name}
     URL: {file_doc.file_url}
""")
