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
	}
}

# Override whitelisted methods
# ------------------
# Intercept PDF download to enforce print gating (block prints of unsigned docs)
override_whitelisted_methods = {
	"frappe.utils.print_format.download_pdf": "e_sign.digital_signature.print_gate.download_pdf",
}

# Permission hooks
# ------------------
has_permission = {
	"DSC Signing Request": "e_sign.digital_signature.permissions.request_has_permission",
	"DSC Profile": "e_sign.digital_signature.permissions.profile_has_permission",
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

# Fixtures — ship roles with the app
# ------------------
fixtures = [
	{
		"dt": "Role",
		"filters": [["name", "in", ["DSC Administrator", "DSC Signer", "DSC Auditor"]]],
	},
]

# Installation
# ------------------
# after_install = "e_sign.install.after_install"

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
