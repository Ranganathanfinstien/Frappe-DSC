app_name = "e_sign"
app_title = "Digital Signature"
app_publisher = "Ragav"
app_description = "DSC digital signing platform for Frappe & ERPNext"
app_email = "prasathragav55@gmail.com"
app_license = "GPL-3.0"

# Required Apps
# ------------------
# required_apps = []

# Global JS/CSS includes
# ------------------
app_include_js = "/assets/e_sign/js/e_sign.js"
app_include_css = "/assets/e_sign/css/e_sign.css"

# DocType-specific JS — adds a "Generate Pairing Code" button on the
# DSC Agent Registration form, plus visual placement preview on the template.
doctype_js = {
	"DSC Agent Registration": "digital_signature/doctype/dsc_agent_registration/dsc_agent_registration.js",
	"DSC Signature Template": "digital_signature/doctype/dsc_signature_template/dsc_signature_template.js",
	# NOTE: do NOT add "DSC Document Sign" here — a JS file inside the doctype's
	# own folder (dsc_document_sign.js) is auto-loaded as its client script.
	# Listing it in doctype_js too would load it twice and crash the form with
	# a "redeclaration of const" SyntaxError.
}

# Document Events — universal listener for the Rules Engine
# ------------------
# The "*" key means this fires on every DocType.
# The rule_engine filters by checking if a DSC Rule exists for the DocType.
doc_events = {
	"*": {
		"on_submit": "e_sign.digital_signature.rule_engine.evaluate_on_submit",
		"on_update_after_submit": "e_sign.digital_signature.rule_engine.evaluate_on_update",
		"on_change": "e_sign.digital_signature.rule_engine.evaluate_on_change",
	},
	"File": {
		# Refuse deletion of DSC-signed PDFs by non-administrators (PRD §12.6)
		"before_delete": "e_sign.digital_signature.file_protection.before_delete",
	},
}

# Override whitelisted methods
# ------------------
# Intercept PDF download to enforce print gating (block prints of unsigned docs)
# Intercept email sending to enforce email gating (PRD §12.4)
override_whitelisted_methods = {
	"frappe.utils.print_format.download_pdf": "e_sign.digital_signature.print_gate.download_pdf",
	"frappe.core.doctype.communication.email.make": "e_sign.digital_signature.email_gate.make",
}

# Permission hooks
# ------------------
has_permission = {
	"DSC Signing Request": "e_sign.digital_signature.permissions.request_has_permission",
	"DSC Profile": "e_sign.digital_signature.permissions.profile_has_permission",
}

permission_query_conditions = {
	"DSC Signing Request": "e_sign.digital_signature.permissions.request_query_conditions",
}

# Scheduled Tasks
# ------------------
scheduler_events = {
	"daily": [
		"e_sign.digital_signature.cert_expiry.notify_upcoming_expiries",
		"e_sign.digital_signature.retention.purge_old_requests",
	],
	"hourly": [
		"e_sign.digital_signature.cleanup.expire_stale_pending_requests",
	],
}

# Fixtures — ship roles + email templates with the app
# ------------------
fixtures = [
	{
		"dt": "Role",
		"filters": [["name", "in", ["DSC Administrator", "DSC Signer", "DSC Auditor"]]],
	},
]

# Installation
# ------------------
after_install = "e_sign.install.after_install"

# Developer hooks (PRD §6.6, §10.5)
# Other apps can register handlers like:
#     dsc_before_sign  = "myapp.dsc_hooks.before_sign"
#     dsc_after_sign   = "myapp.dsc_hooks.after_sign"
#     dsc_on_decline   = "myapp.dsc_hooks.on_decline"
# These are surfaced via api/signing.py's _run_dev_hooks helper.

# Jinja
# ------------------
# jinja = {
# 	"methods": "e_sign.utils.jinja_methods",
# }

# User Data Protection
# ------------------
# user_data_fields = []

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True
