"""End-to-end signing demo with mocked desktop agent.

Generates a self-signed RSA cert, registers it in Department Head profile,
drives initiate -> signs hash in Python (mocks agent) -> drives finalize,
and prints all state transitions + final output.
"""

import base64
import hashlib

import frappe
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from datetime import datetime, timedelta, timezone


def run():
	print("\n" + "=" * 70)
	print("DSC END-TO-END DEMO (mocked desktop agent)")
	print("=" * 70)

	# --- Step 1: Fix rule + ensure a signature template so visible stamp renders ----
	print("\n[1] Preparing demo data")
	rule_name = "Sign Submitted ToDo"
	template_name = "ToDo Bottom Right"
	pf_name = "ToDo Default"

	# DSC Signature Template requires a real Print Format record; create one for ToDo.
	if not frappe.db.exists("Print Format", pf_name):
		frappe.get_doc({
			"doctype": "Print Format",
			"name": pf_name,
			"doc_type": "ToDo",
			"print_format_type": "Jinja",
			"standard": "No",
			"html": "{% include 'templates/print_formats/standard.html' %}",
		}).insert(ignore_permissions=True)
		frappe.db.commit()
		print(f"    Created Print Format '{pf_name}' for ToDo")

	if not frappe.db.exists("DSC Signature Template", template_name):
		tmpl = frappe.get_doc({
			"doctype": "DSC Signature Template",
			"template_name": template_name,
			"target_doctype": "ToDo",
			"print_format": pf_name,
			"is_active": 1,
			"stamp_show_signer_name": 1,
			"stamp_show_designation": 1,
			"stamp_show_digitally_signed_by": 1,
			"stamp_show_timestamp": 1,
			"stamp_timestamp_format": "%d-%m-%Y %H:%M:%S",
			"stamp_show_reason": 1,
			"stamp_show_location": 1,
			"stamp_font_size": 8.0,
			"stamp_border": 1,
			"fields": [{
				"field_name": "primary",
				"page_number": 1,
				"x": 350.0,
				"y": 680.0,
				"width": 200.0,
				"height": 80.0,
			}],
		}).insert(ignore_permissions=True)
		frappe.db.commit()
		print(f"    Created signature template '{template_name}'")
	else:
		print(f"    Signature template '{template_name}' already exists")

	frappe.db.set_value("DSC Rule", rule_name, "print_format", "Standard")
	frappe.db.set_value("DSC Rule", rule_name, "profile", "Department Head")
	frappe.db.set_value("DSC Rule", rule_name, "signature_template", template_name)
	frappe.db.commit()
	print(f"    Rule '{rule_name}' print_format=Standard, profile=Department Head, template={template_name}")

	# --- Step 2: Generate RSA key + self-signed cert ----
	print("\n[2] Generating test RSA-2048 key + self-signed cert")
	private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

	subject = issuer = x509.Name([
		x509.NameAttribute(NameOID.COUNTRY_NAME, "IN"),
		x509.NameAttribute(NameOID.ORGANIZATION_NAME, "E-Sign Demo"),
		x509.NameAttribute(NameOID.COMMON_NAME, "DEPARTMENT HEAD"),
	])
	cert = (
		x509.CertificateBuilder()
		.subject_name(subject)
		.issuer_name(issuer)
		.public_key(private_key.public_key())
		.serial_number(x509.random_serial_number())
		.not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
		.not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
		.add_extension(
			x509.KeyUsage(
				digital_signature=True, content_commitment=True, key_encipherment=False,
				data_encipherment=False, key_agreement=False, key_cert_sign=False,
				crl_sign=False, encipher_only=False, decipher_only=False,
			),
			critical=True,
		)
		.sign(private_key, hashes.SHA256())
	)
	cert_der = cert.public_bytes(serialization.Encoding.DER)
	cert_der_b64 = base64.b64encode(cert_der).decode()
	fingerprint = hashlib.sha256(cert_der).hexdigest()
	print(f"    Cert CN=DEPARTMENT HEAD, fingerprint={fingerprint[:16]}...")

	# --- Step 3: Register cert in Department Head profile ----
	print("\n[3] Registering cert in 'Department Head' DSC Profile")
	# Direct update (bypass api.agent.register_certificate — it has a tz-datetime bug)
	profile = frappe.get_doc("DSC Profile", "Department Head")
	profile.certificate_fingerprint = fingerprint
	profile.certificate_common_name = "DEPARTMENT HEAD"
	profile.certificate_issuer = "CN=DEPARTMENT HEAD (self-signed demo)"
	profile.certificate_serial = format(cert.serial_number, "X")
	profile.certificate_not_before = cert.not_valid_before_utc.replace(tzinfo=None)
	profile.certificate_not_after = cert.not_valid_after_utc.replace(tzinfo=None)
	profile.certificate_pem_public = cert.public_bytes(serialization.Encoding.PEM).decode()
	profile.registered_on = datetime.now().replace(tzinfo=None)
	profile.save(ignore_permissions=True)
	frappe.db.commit()
	print(f"    Registered: CN={profile.certificate_common_name}, expires={profile.certificate_not_after}")

	# --- Step 4: Ensure a Pending signing request exists ----
	print("\n[4] Ensuring Pending DSC Signing Request exists")
	pending = frappe.db.get_value(
		"DSC Signing Request",
		{"status": "Pending", "source_doctype": "ToDo"},
		["name", "source_name"],
		as_dict=True,
	)
	if not pending:
		# Rule engine dedupe blocks new requests for (source, rule) pairs with any
		# prior request. Create a fresh ToDo to trigger a clean rule evaluation.
		new_todo = frappe.get_doc({
			"doctype": "ToDo",
			"description": f"E2E demo document {datetime.now()}",
			"status": "Open",
		}).insert(ignore_permissions=True)
		frappe.db.commit()
		pending = frappe.db.get_value(
			"DSC Signing Request",
			{"status": "Pending", "source_doctype": "ToDo", "source_name": new_todo.name},
			["name", "source_name"],
			as_dict=True,
		)
	print(f"    Pending request: {pending.name} (source=ToDo/{pending.source_name})")

	# --- Step 5: Call initiate() — server prepares PDF + hash ----
	print("\n[5] Calling initiate() — server generates PDF + computes hash")
	frappe.set_user("Administrator")
	from e_sign.api.signing import initiate
	init_result = initiate("ToDo", pending.source_name)
	session_id = init_result["session_id"]
	hash_to_sign_hex = init_result["hash_to_sign"]
	print(f"    session_id: {session_id}")
	print(f"    hash_to_sign (sha256, hex): {hash_to_sign_hex[:32]}...")
	print(f"    expected_cert_fingerprint: {init_result['expected_cert_fingerprint'][:16]}...")
	print(f"    signer_name: {init_result['visual_metadata']['signer_name']}")

	# --- Step 6: MOCK AGENT — sign the hash with our test key ----
	print("\n[6] MOCK AGENT: signing hash with test private key (RSA PKCS#1 v1.5)")
	hash_bytes = bytes.fromhex(hash_to_sign_hex)
	signature_bytes = private_key.sign(
		hash_bytes,
		padding.PKCS1v15(),
		hashes.SHA256(),
	)
	signature_b64 = base64.b64encode(signature_bytes).decode()
	print(f"    signature ({len(signature_bytes)} bytes): {signature_b64[:40]}...")

	# --- Step 7: Call finalize() — server injects sig into PDF ----
	print("\n[7] Calling finalize() — server injects signature, verifies, saves")
	from e_sign.api.signing import finalize
	try:
		final_result = finalize(
			session_id=session_id,
			signature_bytes_b64=signature_b64,
			cert_der_b64=cert_der_b64,
		)
		print(f"    Status: {final_result['status']}")
		print(f"    File name: {final_result['file_name']}")
		print(f"    File URL: {final_result['file_url']}")
		print(f"    Signing request: {final_result['signing_request']}")
		verification = final_result.get("verification", {})
		print(f"    Verification: is_valid={verification.get('is_valid')}, sig_count={verification.get('signature_count')}")
	except Exception as e:
		print(f"    FINALIZE FAILED: {type(e).__name__}: {e}")
		import traceback
		traceback.print_exc()

	# --- Step 8: Show final request state + audit trail ----
	print("\n[8] Final state")
	req = frappe.db.get_value(
		"DSC Signing Request",
		pending.name,
		["name", "status", "signed_on", "signed_file", "failure_reason", "sign_duration_seconds"],
		as_dict=True,
	)
	print(f"    DSC Signing Request: {req}")

	audit = frappe.get_all(
		"DSC Audit Event",
		filters={"request": pending.name},
		fields=["event_type", "occurred_at"],
		order_by="occurred_at asc",
	)
	print(f"\n    Audit trail ({len(audit)} events):")
	for a in audit:
		print(f"      - {a.occurred_at} | {a.event_type}")

	files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "ToDo", "attached_to_name": pending.source_name},
		fields=["name", "file_name", "file_url", "file_size"],
	)
	print(f"\n    Attached files on ToDo/{pending.source_name}: {len(files)}")
	for f in files:
		print(f"      - {f.file_name} ({f.file_size} bytes) -> {f.file_url}")

	print("\n" + "=" * 70)
	print("DEMO COMPLETE")
	print("=" * 70 + "\n")
