"""
Rules Engine - evaluates DSC Rules against document events.

Called from doc_events hooks on every DocType. Filters by checking
if a DSC Rule exists for the DocType, evaluates conditions, and
creates DSC Signing Requests on match.
"""

import frappe
from frappe.utils import cint, flt


def evaluate_on_submit(doc, method):
	"""Called from doc_events["*"]["on_submit"] hook.
	Fetch all enabled DSC Rules where target_doctype matches doc.doctype,
	trigger_event is on_submit. Order by priority ascending.
	First match wins (MVP). If match found, call create_signing_request().
	"""
	_evaluate_rules(doc, trigger_event="on_submit")


def evaluate_on_update(doc, method):
	"""Called from doc_events["*"]["on_update_after_submit"] hook.
	Same pattern for on_update trigger event.
	"""
	_evaluate_rules(doc, trigger_event="on_update")


def evaluate_on_change(doc, method):
	"""Called from doc_events["*"]["on_change"] hook.
	Handles on_workflow_action rules by checking workflow_state changes.
	"""
	if not doc.get("workflow_state"):
		return

	# Only fire if workflow_state actually changed
	prev_state = doc.get_doc_before_save()
	if prev_state and prev_state.get("workflow_state") == doc.workflow_state:
		return

	_evaluate_rules(doc, trigger_event="on_workflow_action")


def _evaluate_rules(doc, trigger_event):
	"""Core rule evaluation logic. Fetches matching rules, evaluates conditions,
	and creates a signing request for the first match.
	"""
	rules = get_matching_rules(doc.doctype, trigger_event)

	for rule in rules:
		# Company scoping: skip if rule is company-specific and doesn't match
		if rule.company and rule.company != doc.get("company"):
			continue

		# For workflow_action rules, check the target workflow state
		if trigger_event == "on_workflow_action":
			if rule.trigger_workflow_state and rule.trigger_workflow_state != doc.get("workflow_state"):
				continue

		if evaluate_conditions(rule, doc):
			create_signing_request(doc, rule)
			return  # First match wins (MVP)


def get_matching_rules(doctype, trigger_event):
	"""Fetch all enabled DSC Rules for the given doctype and trigger event,
	ordered by priority ascending.
	"""
	rules = frappe.get_all(
		"DSC Rule",
		filters={
			"is_enabled": 1,
			"target_doctype": doctype,
			"trigger_event": trigger_event,
		},
		order_by="priority asc",
	)

	return [frappe.get_doc("DSC Rule", r.name) for r in rules]


def evaluate_conditions(rule, doc):
	"""Check each DSC Rule Condition row against doc fields.
	Short-circuit AND: all conditions must pass.
	Returns True if all conditions match (or if there are no conditions).
	"""
	if not rule.conditions:
		return True

	for condition in rule.conditions:
		if not _check_condition(condition, doc):
			return False

	return True


def _check_condition(condition, doc):
	"""Evaluate a single condition against a document field."""
	field_value = doc.get(condition.field)
	operator = condition.operator
	target_value = condition.value or ""

	if operator == "is_set":
		return field_value is not None and field_value != "" and field_value != 0

	if operator == "is_not_set":
		return field_value is None or field_value == "" or field_value == 0

	if operator == "equals":
		return _coerce_and_compare(field_value, target_value, "eq")

	if operator == "not_equals":
		return _coerce_and_compare(field_value, target_value, "ne")

	if operator == "greater_than":
		return _coerce_and_compare(field_value, target_value, "gt")

	if operator == "less_than":
		return _coerce_and_compare(field_value, target_value, "lt")

	if operator == "in":
		values = [v.strip() for v in target_value.split(",")]
		return str(field_value) in values

	if operator == "not_in":
		values = [v.strip() for v in target_value.split(",")]
		return str(field_value) not in values

	if operator == "contains":
		return target_value in str(field_value or "")

	return False


def _coerce_and_compare(field_value, target_value, op):
	"""Compare values with type coercion. Tries numeric comparison first,
	falls back to string comparison.
	"""
	try:
		fv = flt(field_value)
		tv = flt(target_value)
		if op == "eq":
			return fv == tv
		if op == "ne":
			return fv != tv
		if op == "gt":
			return fv > tv
		if op == "lt":
			return fv < tv
	except (ValueError, TypeError):
		pass

	# String comparison fallback
	fv = str(field_value or "")
	tv = str(target_value or "")
	if op == "eq":
		return fv == tv
	if op == "ne":
		return fv != tv
	if op == "gt":
		return fv > tv
	if op == "lt":
		return fv < tv

	return False


def create_signing_request(doc, rule):
	"""Create a DSC Signing Request if one doesn't already exist
	for the (doctype, docname, rule) combination.
	Idempotent: re-triggering does not create duplicates.
	"""
	existing = frappe.db.exists("DSC Signing Request", {
		"source_doctype": doc.doctype,
		"source_name": doc.name,
		"rule": rule.name,
	})

	if existing:
		return

	signing_request = frappe.get_doc({
		"doctype": "DSC Signing Request",
		"source_doctype": doc.doctype,
		"source_name": doc.name,
		"rule": rule.name,
		"profile": rule.profile,
		"signature_template": rule.signature_template,
		"expected_signer_user": rule.profile,
		"status": "Pending",
	})
	signing_request.insert(ignore_permissions=True)

	frappe.msgprint(
		f"DSC Signing Request created for {doc.doctype} {doc.name}",
		indicator="blue",
		alert=True,
	)
