import frappe


def run():
	todo_name = frappe.db.get_value("ToDo", {"status": "Open"}, "name")
	print(f"ToDo: {todo_name}")

	rules = frappe.get_all(
		"DSC Rule",
		filters={"is_enabled": 1, "target_doctype": "ToDo"},
		fields=["name", "trigger_event", "company"],
	)
	print(f"Rules found: {rules}")

	if not todo_name or not rules:
		print("Missing ToDo or Rule - aborting")
		return

	from e_sign.digital_signature.rule_engine import evaluate_on_change

	doc = frappe.get_doc("ToDo", todo_name)
	try:
		evaluate_on_change(doc, "on_change")
		frappe.db.commit()
		print("evaluate_on_change completed without error")
	except Exception as e:
		import traceback

		print(f"EXCEPTION: {e}")
		traceback.print_exc()

	result = frappe.db.get_all(
		"DSC Signing Request",
		filters={"source_doctype": "ToDo", "source_name": todo_name},
		fields=["name", "status", "rule"],
	)
	print(f"Signing Requests: {result}")
