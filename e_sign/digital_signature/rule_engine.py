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

	Evaluates two trigger events:
	1. on_change — fires on every save (covers non-submittable DocTypes like ToDo, Customer, etc.)
	2. on_workflow_action — fires only when workflow_state actually changes
	"""
	_evaluate_rules(doc, trigger_event="on_change")

	if not doc.get("workflow_state"):
		return

	prev_state = doc.get_doc_before_save()
	if prev_state and prev_state.get("workflow_state") == doc.workflow_state:
		return

	_evaluate_rules(doc, trigger_event="on_workflow_action")


def _evaluate_rules(doc, trigger_event):
	"""Core rule evaluation logic. Fetches matching rules, evaluates conditions,
	and creates a signing request for the first match.
	"""
	logger = frappe.logger("e_sign")
	rules = get_matching_rules(doc.doctype, trigger_event)

	if not rules:
		# No match is the common case (hook fires on every doctype save) — stay silent.
		return

	logger.info(
		f"[DSC] Evaluating {len(rules)} rule(s) for {doc.doctype} {doc.name} "
		f"(trigger={trigger_event})"
	)

	for rule in rules:
		if rule.company and rule.company != doc.get("company"):
			logger.info(
				f"[DSC] Rule {rule.name} skipped: company mismatch "
				f"(rule={rule.company}, doc={doc.get('company')})"
			)
			continue

		if trigger_event == "on_workflow_action":
			if rule.trigger_workflow_state and rule.trigger_workflow_state != doc.get("workflow_state"):
				logger.info(
					f"[DSC] Rule {rule.name} skipped: workflow_state mismatch "
					f"(rule={rule.trigger_workflow_state}, doc={doc.get('workflow_state')})"
				)
				continue

		matched = evaluate_conditions(rule, doc)
		if matched:
			req_name = create_signing_request(doc, rule)
			# Rule Evaluated + Template Selected events (PRD §F7.2) — emitted
			# only after the request exists, since DSC Audit Event requires a
			# signing_request reference.
			if req_name:
				from e_sign.digital_signature.audit import log_event
				log_event(req_name, "Rule Evaluated", {
					"rule": rule.name,
					"matched": True,
					"trigger_event": trigger_event,
					"priority": rule.priority,
				})
				if rule.signature_template:
					log_event(req_name, "Template Selected", {
						"template": rule.signature_template,
					})
			return  # First match wins (MVP)
		else:
			logger.info(
				f"[DSC] Rule {rule.name} skipped: conditions did not match for "
				f"{doc.doctype} {doc.name}"
			)


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

	frappe.logger("e_sign").warning(
		f"[DSC] Unknown condition operator '{operator}' on field '{condition.field}' "
		f"— condition treated as False"
	)
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

	Returns the request name (existing or newly created) so callers can
	emit follow-on audit events against it.
	"""
	from e_sign.digital_signature.audit import log_event

	existing = frappe.db.exists("DSC Signing Request", {
		"source_doctype": doc.doctype,
		"source_name": doc.name,
		"rule": rule.name,
	})

	if existing:
		return existing

	expected_signer = _resolve_signer_user(rule.profile)

	signing_request = frappe.get_doc({
		"doctype": "DSC Signing Request",
		"source_doctype": doc.doctype,
		"source_name": doc.name,
		"rule": rule.name,
		"profile": rule.profile,
		"signature_template": rule.signature_template,
		"expected_signer_user": expected_signer,
		"status": "Pending",
	})
	signing_request.insert(ignore_permissions=True)

	frappe.logger("e_sign").info(
		f"[DSC] Created Signing Request {signing_request.name} for "
		f"{doc.doctype} {doc.name} via rule {rule.name}"
	)

	# PRD §F7.2 — Request Created audit event
	log_event(signing_request.name, "Request Created", {
		"source_doctype": doc.doctype,
		"source_name": doc.name,
		"rule": rule.name,
		"profile": rule.profile,
		"expected_signer_user": expected_signer,
	})

	# PRD §F8.1 — notify the expected signer by email so they don't miss the request
	if expected_signer and expected_signer != "Administrator":
		try:
			_notify_signer(signing_request.name, doc, rule, expected_signer)
		except Exception:
			frappe.log_error(title="DSC: signer notification email failed")

		try:
			_assign_signer_todo(signing_request.name, doc, expected_signer)
		except Exception:
			frappe.log_error(title="DSC: signer ToDo assignment failed")

	frappe.msgprint(
		f"DSC Signing Request created for {doc.doctype} {doc.name}",
		indicator="blue",
		alert=True,
	)

	return signing_request.name


def _notify_signer(signing_request_name, source_doc, rule, signer_user):
	"""Email the expected signer that a document is awaiting their signature."""
	site_url = frappe.utils.get_url()
	frappe.sendmail(
		recipients=[signer_user],
		subject=f"Action required: sign {source_doc.doctype} {source_doc.name}",
		message=(
			f"<p>A new document is awaiting your digital signature.</p>"
			f"<ul>"
			f"<li><b>Document:</b> {source_doc.doctype} {source_doc.name}</li>"
			f"<li><b>Rule:</b> {rule.name}</li>"
			f"<li><b>Profile:</b> {rule.profile}</li>"
			f"</ul>"
			f"<p><a href='{site_url}/app/{frappe.scrub(source_doc.doctype).replace('_', '-')}/{source_doc.name}'>"
			f"Open document</a> and click <b>Sign with DSC</b>.</p>"
		),
		now=True,
	)


def _assign_signer_todo(signing_request_name, source_doc, signer_user):
	"""Create a ToDo on the DSC Signing Request assigned to the signer.

	notify=False because _notify_signer() already sent a richer custom email —
	we don't want the signer to receive Frappe's generic assignment notice too.
	"""
	from frappe.desk.form.assign_to import add as assign_add

	assign_add({
		"assign_to": [signer_user],
		"doctype": "DSC Signing Request",
		"name": signing_request_name,
		"description": f"Sign {source_doc.doctype} {source_doc.name}",
		"notify": 0,
		"priority": "Medium",
	})


def _resolve_signer_user(profile_name):
	"""Resolve the expected signer user from a DSC Profile's allowed_users.

	Returns the first allowed user. If the current user is in the allowed list,
	prefer them. Returns None if no users are configured.
	"""
	allowed_users = frappe.get_all(
		"DSC Profile User",
		filters={"parent": profile_name, "parenttype": "DSC Profile"},
		fields=["user"],
		order_by="idx asc",
	)

	if not allowed_users:
		return None

	# If current user is in the list, prefer them
	current_user = frappe.session.user
	for row in allowed_users:
		if row.user == current_user:
			return current_user

	# Otherwise return the first allowed user
	return allowed_users[0].user
