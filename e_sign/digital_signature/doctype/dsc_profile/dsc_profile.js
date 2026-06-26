/**
 * DSC Profile — form client script.
 *
 * Adds a "Register Certificate" button that reads the certificate from the
 * token plugged into the local dsc-bridge agent and registers it against this
 * profile. The server (e_sign.api.agent.register_certificate) computes the
 * SHA-256 fingerprint from the certificate DER and stores it — the fingerprint
 * is NEVER entered by hand. This is the only supported way to populate the
 * Certificate Fingerprint field.
 */

frappe.ui.form.on("DSC Profile", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Register Certificate"), () => {
			register_certificate_from_token(frm);
		});

		if (frm.doc.certificate_fingerprint) {
			frm.dashboard.set_headline(
				__("Certificate registered: {0}", [
					frm.doc.certificate_common_name || frm.doc.certificate_fingerprint.slice(0, 16) + "…",
				])
			);
		}
	},
});

// dsc-bridge agent — same host/port the global signing script uses.
const AGENT_HOST = "127.0.0.1";
const DEFAULT_AGENT_PORT = 4645;

function get_site_token() {
	return window.localStorage.getItem("dsc_site_token") || "";
}

async function fetch_token_certs() {
	const url = `https://${AGENT_HOST}:${DEFAULT_AGENT_PORT}/v1/certs`;
	let resp;
	try {
		resp = await fetch(url, {
			method: "GET",
			mode: "cors",
			headers: { "X-DSC-Site-Token": get_site_token() },
		});
	} catch (e) {
		throw new Error(
			__("Cannot reach the dsc-bridge agent at {0}. Is it running and is the token plugged in?", [url])
		);
	}
	if (!resp.ok) {
		throw new Error(__("The agent could not read certificates from the token (HTTP {0}).", [resp.status]));
	}
	const body = await resp.json();
	const certs = (body && body.certs) || [];
	if (!certs.length) {
		throw new Error(__("No certificate found on the connected token."));
	}
	return certs;
}

function register_selected(frm, cert) {
	if (!cert || !cert.cert_der_b64) {
		frappe.msgprint({
			title: __("Cannot register"),
			message: __("The selected certificate did not include its DER data. Update the dsc-bridge agent."),
			indicator: "red",
		});
		return;
	}
	frappe.call({
		method: "e_sign.api.agent.register_certificate",
		args: {
			profile_name: frm.doc.name,
			cert_der_b64: cert.cert_der_b64,
		},
		freeze: true,
		freeze_message: __("Registering certificate…"),
		callback: (r) => {
			if (!r.exc) {
				frappe.show_alert({
					message: __("Certificate registered for {0}", [r.message.common_name || frm.doc.name]),
					indicator: "green",
				});
				frm.reload_doc();
			}
		},
	});
}

async function register_certificate_from_token(frm) {
	let certs;
	try {
		certs = await fetch_token_certs();
	} catch (e) {
		frappe.msgprint({ title: __("Register Certificate"), message: e.message, indicator: "red" });
		return;
	}

	if (certs.length === 1) {
		register_selected(frm, certs[0]);
		return;
	}

	// Multiple certificates on the token — let the admin choose which to bind.
	const d = new frappe.ui.Dialog({
		title: __("Select certificate to register"),
		fields: [
			{
				fieldname: "cert_idx",
				fieldtype: "Select",
				label: __("Certificate"),
				reqd: 1,
				options: certs.map((c, i) => ({
					label: `${c.subject_cn || c.subject_full || __("Certificate")} — ${c.issuer_cn || ""} (${(c.fingerprint_sha256 || "").slice(0, 12)}…)`,
					value: String(i),
				})),
			},
		],
		primary_action_label: __("Register"),
		primary_action(values) {
			d.hide();
			register_selected(frm, certs[Number(values.cert_idx)]);
		},
	});
	d.show();
}
