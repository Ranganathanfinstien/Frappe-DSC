"""
One-shot demo data setup for the DSC signing flow.

Run from bench:

    bench --site sign.local execute e_sign.setup_demo.run

Idempotent: re-running updates rather than duplicates.
Cleanup:

    bench --site sign.local execute e_sign.setup_demo.teardown
"""

import frappe
from frappe.utils import now_datetime

PROFILE_NAME = "RAJESH-CFO-2026"
TEMPLATE_NAME = "Sales Invoice Bottom Right"
RULE_NAME = "Sign all Sales Invoices over 50K"


def run():
	"""Create the full demo data set and report what was made."""
	report = []

	user = _pick_user()
	company = _pick_company()
	report.append(f"Using user: {user}")
	report.append(f"Using company: {company}")

	_settings()
	report.append("[ok] DSC Settings configured")

	_profile(user=user, company=company)
	report.append(f"[ok] DSC Profile: {PROFILE_NAME}")

	_template()
	report.append(f"[ok] DSC Signature Template: {TEMPLATE_NAME}")

	_rule(company=company)
	report.append(f"[ok] DSC Rule: {RULE_NAME}")

	frappe.db.commit()

	print("\n".join(report))
	print("\nNext: submit a Sales Invoice with grand_total >= 50000 and check")
	print("/app/dsc-signing-request — a row with status 'Pending' should appear.")


def teardown():
	"""Remove the demo records."""
	for dt, name in [
		("DSC Rule", RULE_NAME),
		("DSC Signature Template", TEMPLATE_NAME),
		("DSC Profile", PROFILE_NAME),
	]:
		if frappe.db.exists(dt, name):
			frappe.delete_doc(dt, name, force=1, ignore_permissions=True)
			print(f"[deleted] {dt}: {name}")
		else:
			print(f"[skip] {dt}: {name} not found")
	frappe.db.commit()


def test_flow():
	"""End-to-end smoke test of the rule engine.

	Creates a throwaway Customer + Item if needed, submits two Sales Invoices
	(one above the 50K threshold, one below), and verifies the rule engine
	creates a DSC Signing Request only for the qualifying one.
	"""
	company = _pick_company()
	if not company:
		print("FAIL: no Company found — set up ERPNext first.")
		return

	customer = _ensure_customer()
	item = _ensure_item()
	print(f"Using customer: {customer}")
	print(f"Using item: {item}")

	# Case A — above threshold, should produce a Signing Request
	above = _make_invoice(customer=customer, item=item, company=company, qty=1, rate=75000)
	# Case B — below threshold, should NOT produce one
	below = _make_invoice(customer=customer, item=item, company=company, qty=1, rate=20000)

	frappe.db.commit()

	above_req = frappe.db.exists(
		"DSC Signing Request",
		{"source_doctype": "Sales Invoice", "source_name": above},
	)
	below_req = frappe.db.exists(
		"DSC Signing Request",
		{"source_doctype": "Sales Invoice", "source_name": below},
	)

	print()
	print(f"Invoice above 50K ({above}): signing request created = {bool(above_req)}")
	if above_req:
		req = frappe.get_doc("DSC Signing Request", above_req)
		print(f"  request name:   {req.name}")
		print(f"  status:         {req.status}")
		print(f"  rule:           {req.rule}")
		print(f"  profile:        {req.profile}")
		print(f"  expected user:  {req.expected_signer_user}")

	print(f"Invoice below 50K ({below}): signing request created = {bool(below_req)}")

	if above_req and not below_req:
		print("\nPASS — rule engine fired correctly on threshold.")
	else:
		print("\nFAIL — rule engine behaviour does not match expectations.")


def test_pairing():
	"""Smoke test for the agent pairing flow.

	Generates a pairing code, then exchanges it for a site token using a fake
	agent fingerprint — the same handshake dsc-bridge performs.
	"""
	from e_sign.api import agent

	gen = agent.generate_pairing_code()
	print(f"generated code: {gen['pairing_code']}")
	print(f"site_url:       {gen['site_url']}")
	print(f"expires_in:     {gen['expires_in_seconds']}s")

	fake_fp = "deadbeef" * 8  # 64-char hex fake fingerprint
	result = agent.validate_pairing_code(
		pairing_code=gen["pairing_code"],
		agent_fingerprint=fake_fp,
		os_platform="linux",
		agent_version="1.0.0-demo",
	)
	print()
	print(f"status:               {result['status']}")
	print(f"agent_registration:   {result['agent_registration']}")
	print(f"site_token (prefix):  {result['site_token'][:16]}…")

	frappe.db.commit()

	reg = frappe.get_doc("DSC Agent Registration", result["agent_registration"])
	print()
	print(f"Registration record stored:")
	print(f"  user:               {reg.user}")
	print(f"  agent_fingerprint:  {reg.agent_fingerprint}")
	print(f"  os_platform:        {reg.os_platform}")
	print(f"  agent_version:      {reg.agent_version}")
	print(f"  is_active:          {reg.is_active}")

	print("\nPASS — pairing handshake completed and registration stored.")


def _ensure_customer() -> str:
	name = "DSC Demo Customer"
	if not frappe.db.exists("Customer", name):
		frappe.get_doc({
			"doctype": "Customer",
			"customer_name": name,
			"customer_type": "Company",
			"customer_group": frappe.db.get_value("Customer Group", {}, "name") or "All Customer Groups",
			"territory": frappe.db.get_value("Territory", {}, "name") or "All Territories",
		}).insert(ignore_permissions=True)
	return name


def _ensure_item() -> str:
	code = "DSC-DEMO-ITEM"
	if not frappe.db.exists("Item", code):
		frappe.get_doc({
			"doctype": "Item",
			"item_code": code,
			"item_name": "DSC Demo Service",
			"item_group": frappe.db.get_value("Item Group", {}, "name") or "All Item Groups",
			"stock_uom": "Nos",
			"is_stock_item": 0,
		}).insert(ignore_permissions=True)
	return code


def _make_invoice(customer: str, item: str, company: str, qty: float, rate: float) -> str:
	doc = frappe.get_doc({
		"doctype": "Sales Invoice",
		"customer": customer,
		"company": company,
		"due_date": frappe.utils.add_days(frappe.utils.today(), 30),
		"items": [
			{
				"item_code": item,
				"qty": qty,
				"rate": rate,
				"income_account": frappe.db.get_value(
					"Account",
					{"company": company, "account_type": "Income Account", "is_group": 0},
					"name",
				),
			}
		],
		"update_stock": 0,
	})
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def _pick_user() -> str:
	# Prefer a real signer over Administrator
	candidate = frappe.db.get_value(
		"User",
		filters={"enabled": 1, "name": ["not in", ["Administrator", "Guest"]]},
		fieldname="name",
		order_by="creation asc",
	)
	return candidate or "Administrator"


def _pick_company() -> str | None:
	return frappe.db.get_value("Company", filters={}, fieldname="name", order_by="creation asc")


def _settings():
	doc = frappe.get_single("DSC Settings")
	doc.default_reason = "Approved by Authorised Signatory"
	doc.default_location = "Chennai, IN"
	doc.signing_timeout_seconds = 180
	doc.retention_years_for_requests = 7
	doc.agent_listen_port = 4645
	doc.pdf_preparation_engine = "pyhanko"
	doc.default_hash_algorithm = "sha256"
	doc.enable_expiry_warnings = 1

	doc.set("expiry_warning_days", [])
	for d in (30, 15, 7, 1):
		doc.append("expiry_warning_days", {"days": d})

	doc.save(ignore_permissions=True)


def _profile(user: str, company: str | None):
	if frappe.db.exists("DSC Profile", PROFILE_NAME):
		doc = frappe.get_doc("DSC Profile", PROFILE_NAME)
	else:
		doc = frappe.new_doc("DSC Profile")
		doc.profile_name = PROFILE_NAME

	doc.label = "Chief Financial Officer"
	doc.company = company
	doc.is_active = 1
	doc.certificate_fingerprint = (
		"a1b2c3d4e5f60718293a4b5c6d7e8f9012345678901234567890abcdef123456"
	)
	doc.certificate_common_name = "RAJESH KUMAR"
	doc.certificate_issuer = "eMudhra Sub CA for Class 3 Individual 2022"
	doc.certificate_serial = "7A3B2C1D4E5F6A7B"
	doc.certificate_not_before = "2024-03-12 00:00:00"
	doc.certificate_not_after = "2027-03-11 23:59:59"
	doc.designation_for_stamp = "Chief Financial Officer, Acme Corp"
	doc.registered_on = now_datetime()

	doc.set("allowed_users", [])
	doc.append("allowed_users", {"user": user})

	doc.save(ignore_permissions=True)


def _template():
	if frappe.db.exists("DSC Signature Template", TEMPLATE_NAME):
		doc = frappe.get_doc("DSC Signature Template", TEMPLATE_NAME)
	else:
		doc = frappe.new_doc("DSC Signature Template")
		doc.template_name = TEMPLATE_NAME

	doc.target_doctype = "Sales Invoice"
	doc.print_format = _pick_print_format("Sales Invoice")
	doc.version = 1
	doc.is_active = 1

	doc.stamp_show_signer_name = 1
	doc.stamp_show_designation = 1
	doc.stamp_show_digitally_signed_by = 1
	doc.stamp_show_timestamp = 1
	doc.stamp_timestamp_format = "%d-%m-%Y %H:%M:%S %Z"
	doc.stamp_show_reason = 1
	doc.stamp_show_location = 1
	doc.stamp_show_dn_cn = 0
	doc.stamp_include_signature_image = 0
	doc.stamp_include_seal_image = 0
	doc.stamp_font_family = "Helvetica"
	doc.stamp_font_size = 8
	doc.stamp_border = 1

	doc.set("fields", [])
	doc.append(
		"fields",
		{
			"field_name": "primary",
			"page_number": 1,
			"x": 350,
			"y": 60,
			"width": 200,
			"height": 80,
			"assigned_profile": PROFILE_NAME,
		},
	)

	doc.save(ignore_permissions=True)


def _rule(company: str | None):
	if frappe.db.exists("DSC Rule", RULE_NAME):
		doc = frappe.get_doc("DSC Rule", RULE_NAME)
	else:
		doc = frappe.new_doc("DSC Rule")
		doc.rule_name = RULE_NAME

	doc.priority = 10
	doc.is_enabled = 1
	doc.target_doctype = "Sales Invoice"
	doc.trigger_event = "on_submit"
	doc.profile = PROFILE_NAME
	doc.print_format = _pick_print_format("Sales Invoice")
	doc.signature_template = TEMPLATE_NAME
	doc.is_mandatory = 1
	doc.block_print_until_signed = 1
	doc.block_email_until_signed = 0
	doc.auto_attach_to_source = 1
	doc.company = company

	doc.set("conditions", [])
	doc.append(
		"conditions",
		{"field": "grand_total", "operator": "greater_than", "value": "50000"},
	)

	doc.save(ignore_permissions=True)


def _pick_print_format(doctype: str) -> str:
	# Pick any enabled Print Format record for the DocType.
	# "Standard" is a built-in name that isn't always materialised as a record.
	pf = frappe.db.get_value(
		"Print Format",
		filters={"doc_type": doctype, "disabled": 0},
		fieldname="name",
		order_by="standard asc, name asc",
	)
	if not pf:
		frappe.throw(f"No Print Format found for {doctype} — create one first.")
	return pf
