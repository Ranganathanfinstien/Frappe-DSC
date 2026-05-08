import frappe


def run():
	print("\n=== CURRENT STATE ===\n")

	profiles = frappe.get_all(
		"DSC Profile",
		fields=["name", "is_active", "certificate_common_name", "certificate_fingerprint", "certificate_not_after"],
	)
	print(f"DSC Profiles ({len(profiles)}):")
	for p in profiles:
		has_cert = "YES" if p.certificate_fingerprint else "NO"
		print(f"  - {p.name} | active={p.is_active} | has_cert={has_cert} | cn={p.certificate_common_name}")

	rules = frappe.get_all(
		"DSC Rule",
		fields=["name", "is_enabled", "target_doctype", "trigger_event", "profile", "signature_template", "print_format", "company"],
	)
	print(f"\nDSC Rules ({len(rules)}):")
	for r in rules:
		print(f"  - {r.name} | enabled={r.is_enabled} | {r.target_doctype}/{r.trigger_event} | profile={r.profile} | tmpl={r.signature_template} | company={r.company}")

	templates = frappe.get_all(
		"DSC Signature Template",
		fields=["name", "is_active", "target_doctype", "print_format"],
	)
	print(f"\nDSC Signature Templates ({len(templates)}):")
	for t in templates:
		print(f"  - {t.name} | active={t.is_active} | {t.target_doctype} | pf={t.print_format}")

	requests = frappe.get_all(
		"DSC Signing Request",
		fields=["name", "status", "source_doctype", "source_name", "rule", "profile", "signed_file"],
		order_by="creation desc",
		limit=10,
	)
	print(f"\nRecent DSC Signing Requests ({len(requests)}):")
	for sr in requests:
		print(f"  - {sr.name} | {sr.status} | src={sr.source_doctype}/{sr.source_name} | rule={sr.rule} | file={sr.signed_file}")

	todos = frappe.get_all("ToDo", fields=["name", "status", "description"], order_by="creation desc", limit=5)
	print(f"\nRecent ToDos ({len(todos)}):")
	for t in todos:
		desc = (t.description or "")[:60]
		print(f"  - {t.name} | {t.status} | {desc}")
