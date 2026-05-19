// Pairing UI for DSC Agent Registration.
//
// "Pair This Computer" does one-click pairing: the browser asks the server for
// a one-time code, then hands that code straight to the local dsc-bridge agent
// at https://127.0.0.1:<port>/v1/pair — no code to copy, no curl to run. This
// is the same browser-to-localhost-agent pattern e_sign.js uses for signing.
//
// "Show Manual Code" is kept as a fallback for pairing an agent that runs on a
// different machine than the browser.
//
// The whole file is wrapped in an IIFE: this doctype's controller JS is loaded
// more than once (it is both auto-loaded from the doctype folder and listed in
// hooks.py doctype_js), so top-level `const`s would otherwise throw
// "redeclaration of const" and crash the form.

(function () {
"use strict";

const AGENT_HOST = "127.0.0.1";
const DEFAULT_AGENT_PORT = 4645;

frappe.ui.form.on("DSC Agent Registration", {
	refresh(frm) {
		const $pair = frm.add_custom_button(__("Pair This Computer"), () =>
			pairThisComputer(frm)
		);
		$pair.removeClass("btn-default").addClass("btn-primary");

		frm.add_custom_button(
			__("Show Manual Code"),
			() => generateAndShowCode(frm),
			__("More")
		);

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

// ---------------------------------------------------------------------------
// One-click automatic pairing
// ---------------------------------------------------------------------------

async function pairThisComputer(frm) {
	const port = await getAgentPort();
	frappe.dom.freeze(__("Pairing this computer…"));
	try {
		// 1. Confirm the local dsc-bridge agent is reachable.
		const status = await pingAgent(port);
		if (!status) {
			throw new AgentUnreachable(port);
		}

		// 2. Mint a one-time pairing code on the server. site_url is derived
		//    server-side from the site's host_name, so the agent calls back a
		//    URL that actually resolves.
		const codeResp = await callServer("e_sign.api.agent.generate_pairing_code");
		if (!codeResp || !codeResp.pairing_code) {
			throw new Error(__("The server did not return a pairing code."));
		}

		// 3. Hand the code straight to the local agent — it validates the code
		//    against the site and stores the long-lived site token itself.
		const resp = await fetch(`https://${AGENT_HOST}:${port}/v1/pair`, {
			method: "POST",
			mode: "cors",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				pairing_code: codeResp.pairing_code,
				site_url: codeResp.site_url,
			}),
		});
		const body = await resp.json().catch(() => ({}));
		if (!resp.ok) {
			throw new Error(
				body.message ||
					body.error ||
					__("The agent could not complete pairing.")
			);
		}

		frappe.dom.unfreeze();
		frappe.show_alert(
			{ message: __("This computer is paired ✓"), indicator: "green" },
			6
		);
		// validate_pairing_code created a fresh DSC Agent Registration row —
		// drop the user on the list so they see it.
		setTimeout(() => frappe.set_route("List", "DSC Agent Registration"), 900);
	} catch (err) {
		frappe.dom.unfreeze();
		showPairError(err, port);
	}
}

// Marker error so showPairError can give agent-specific guidance.
function AgentUnreachable(port) {
	this.name = "AgentUnreachable";
	this.port = port;
	this.message = __("The DSC Bridge agent is not reachable on this computer.");
}

async function pingAgent(port) {
	try {
		const r = await fetch(`https://${AGENT_HOST}:${port}/v1/status`, {
			method: "GET",
			mode: "cors",
		});
		return r.ok ? await r.json() : null;
	} catch (e) {
		return null;
	}
}

async function getAgentPort() {
	try {
		const v = await frappe.db.get_single_value("DSC Settings", "agent_listen_port");
		return parseInt(v, 10) || DEFAULT_AGENT_PORT;
	} catch (e) {
		return DEFAULT_AGENT_PORT;
	}
}

function callServer(method, args) {
	return new Promise((resolve, reject) => {
		frappe.call({
			method,
			args,
			callback: (r) => resolve(r ? r.message : null),
			error: reject,
		});
	});
}

function showPairError(err, port) {
	const statusUrl = `https://${AGENT_HOST}:${port}/v1/status`;
	let message;
	if (err && err.name === "AgentUnreachable") {
		// Most often: agent not running, or the browser hasn't accepted the
		// agent's self-signed certificate yet.
		message =
			__("The DSC Bridge agent could not be reached on this computer.") +
			"<br><br>" +
			__("Check that:") +
			`<ul>
				<li>${__("the DSC Bridge agent is installed and running")}</li>
				<li>${__("it is listening on port {0}", [port])}</li>
			</ul>` +
			__(
				"If it is running, your browser may be blocking its self-signed certificate. Open {0} once in a new tab, accept the security warning, then click Pair again.",
				[`<a href='${statusUrl}' target='_blank'>${statusUrl}</a>`]
			);
	} else {
		message =
			frappe.utils.escape_html((err && err.message) || String(err)) +
			"<br><br>" +
			__(
				"You can also use <b>More → Show Manual Code</b> to pair an agent running on a different machine."
			);
	}
	frappe.msgprint({ title: __("Pairing failed"), indicator: "red", message });
}

// ---------------------------------------------------------------------------
// Manual pairing (fallback) — for an agent on a different machine
// ---------------------------------------------------------------------------

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

	const curlCmd =
		`curl -k -X POST https://127.0.0.1:4645/v1/pair \\\n` +
		`  -H 'Content-Type: application/json' \\\n` +
		`  -d '${JSON.stringify({ pairing_code: code, site_url: siteUrl })}'`;

	const dlg = new frappe.ui.Dialog({
		title: __("Pair an Agent on Another Machine"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				options: `
					<p>${__(
						"For an agent on <strong>this</strong> computer, just use the <b>Pair This Computer</b> button — it is automatic."
					)}</p>
					<p>${__(
						"To pair an agent on a <strong>different</strong> machine, paste this code into that agent's pairing prompt — or run the curl command below on that machine."
					)}</p>
					<div style='text-align:center'>
						<div class='dsc-pairing-code'>${frappe.utils.escape_html(code)}</div>
						<div class='text-muted'><small id='dsc-ttl'>${ttlText(ttl)}</small></div>
					</div>

					<h6 style='margin-top:20px'>${__("Or run this on the agent host")}</h6>
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

})();
