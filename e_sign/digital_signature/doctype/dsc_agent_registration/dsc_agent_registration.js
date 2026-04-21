// Pairing UI for DSC Agent Registration.
//
// Shows a "Generate Pairing Code" button. Clicking it mints a one-time code
// via e_sign.api.agent.generate_pairing_code, displays it in a big monospace
// box, and shows the curl command the user can paste into the agent.

frappe.ui.form.on("DSC Agent Registration", {
	refresh(frm) {
		frm.add_custom_button(__("Generate Pairing Code"), () => generateAndShowCode(frm));

		if (!frm.is_new() && frm.doc.is_active) {
			frm.add_custom_button(
				__("Revoke Agent"),
				() => {
					frappe.confirm(
						__("Disable this paired agent? It will no longer be able to sign."),
						() => {
							frappe.call({
								method: "e_sign.api.agent.revoke",
								args: { agent_registration: frm.doc.name },
								callback() {
									frappe.show_alert(
										{ message: __("Agent revoked"), indicator: "orange" },
										5
									);
									frm.reload_doc();
								},
							});
						}
					);
				},
				__("Actions")
			);
		}
	},
});

function generateAndShowCode(frm) {
	frappe.call({
		method: "e_sign.api.agent.generate_pairing_code",
		callback(r) {
			if (!r || !r.message) return;
			showPairingDialog(r.message);
		},
	});
}

function showPairingDialog(payload) {
	const code = payload.pairing_code;
	const ttl = payload.expires_in_seconds || 600;
	const siteUrl = payload.site_url || frappe.boot.sitename || window.location.origin;

	// Pretty curl command the user can paste into the agent host
	const curlCmd =
		`curl -k -X POST https://127.0.0.1:4645/v1/pair \\\n` +
		`  -H 'Content-Type: application/json' \\\n` +
		`  -d '${JSON.stringify({ pairing_code: code, site_url: siteUrl })}'`;

	const dlg = new frappe.ui.Dialog({
		title: __("Pair Desktop Agent"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				options: `
					<p>${__(
						"On the machine running <strong>dsc-bridge</strong>, paste this code into the agent's pairing prompt — or run the curl command below."
					)}</p>
					<div style='text-align:center'>
						<div class='dsc-pairing-code'>${frappe.utils.escape_html(code)}</div>
						<div class='text-muted'><small id='dsc-ttl'>${ttlText(ttl)}</small></div>
					</div>

					<h6 style='margin-top:20px'>${__("Or run this in PowerShell / bash on the agent host")}</h6>
					<pre style='background:#f6f8fa;padding:10px;border-radius:4px;font-size:11px'>${frappe.utils.escape_html(
						curlCmd
					)}</pre>

					<p class='text-muted'><small>${__(
						"After successful pairing, a new DSC Agent Registration row will appear automatically."
					)}</small></p>
				`,
			},
		],
		primary_action_label: __("Copy Code"),
		primary_action() {
			navigator.clipboard
				.writeText(code)
				.then(() =>
					frappe.show_alert({ message: __("Code copied"), indicator: "green" }, 3)
				);
		},
	});

	dlg.show();

	// Live countdown — also auto-closes when expired
	let remaining = ttl;
	const tick = setInterval(() => {
		remaining -= 1;
		const $el = dlg.$wrapper.find("#dsc-ttl");
		if (!$el.length) {
			clearInterval(tick);
			return;
		}
		if (remaining <= 0) {
			clearInterval(tick);
			$el.html(`<span class='text-danger'>${__("Code expired — generate a new one")}</span>`);
			return;
		}
		$el.text(ttlText(remaining));
	}, 1000);
}

function ttlText(seconds) {
	const mm = Math.floor(seconds / 60);
	const ss = seconds % 60;
	return __("Expires in {0}m {1}s", [mm, String(ss).padStart(2, "0")]);
}
