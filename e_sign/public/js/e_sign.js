/**
 * e_sign — Global client script for the Digital Signature platform.
 *
 * Loaded on every Desk page via app_include_js.
 * Adds a "Sign with DSC" button to any saved+submitted document for which
 * a pending DSC Signing Request exists, then orchestrates the three-way
 * signing handshake between the browser, the Frappe server, and the local
 * dsc-bridge agent on https://127.0.0.1:<port>.
 */

(function () {
	"use strict";

	// ----- Config -----
	const STATUS_API = "e_sign.api.signing.get_form_actions";
	const INITIATE_API = "e_sign.api.signing.initiate";
	const FINALIZE_API = "e_sign.api.signing.finalize";
	const RETRY_API = "e_sign.api.signing.retry";
	const CANCEL_API = "e_sign.api.signing.cancel";

	const AGENT_HOST = "127.0.0.1";
	const DEFAULT_AGENT_PORT = 4645;

	// Status → indicator colour for the form's "DSC Status" header field
	const STATUS_COLORS = {
		"Awaiting Signature": "orange",
		"Signature In Progress": "blue",
		"Signed": "green",
		"Signing Failed": "red",
		"Not Applicable": "grey",
	};

	// ----- Universal form refresh hook -----
	// Hooks every DocType form via the global form-refresh event that Frappe
	// fires from form.js after each refresh. The status API is cheap (one DB
	// lookup) and returns "Not Applicable" instantly if no rule targets this
	// DocType, so we don't need a per-DocType filter here.
	$(document).on("form-refresh", function (_e, frm) {
		if (!frm || frm.is_new() || !frm.doc || !frm.doc.name) return;
		refreshDscStatus(frm);
	});

	function refreshDscStatus(frm) {
		frappe.call({
			method: STATUS_API,
			args: { doctype: frm.doctype, docname: frm.doc.name },
			callback(r) {
				const info = r && r.message;
				if (!info || info.status === "Not Applicable") return;

				renderStatusIndicator(frm, info);
				renderActionButtons(frm, info);
			},
		});
	}

	function renderStatusIndicator(frm, info) {
		const colour = STATUS_COLORS[info.status] || "grey";
		frm.dashboard.set_headline_alert(
			`<span class="indicator ${colour}">DSC: ${info.status}</span>`
		);
	}

	function renderActionButtons(frm, info) {
		// Always-available secondary actions (history, manual refresh)
		frm.add_custom_button(
			__("View Signing History"),
			() => openHistoryDialog(frm, info),
			__("Digital Signature")
		);

		if (info.can_sign) {
			const $btn = frm.add_custom_button(
				__("Sign with DSC"),
				() => startSigningFlow(frm, info),
				__("Digital Signature")
			);
			$btn.removeClass("btn-default").addClass("btn-primary");
		}

		const failed = (info.signing_requests || []).filter((r) => r.status === "Failed");
		if (failed.length) {
			frm.add_custom_button(
				__("Retry Last Failed"),
				() => retryLastFailed(frm, failed),
				__("Digital Signature")
			);
		}
	}

	// ============================================================
	//                         SIGNING FLOW
	// ============================================================

	function startSigningFlow(frm, info) {
		const port = info.agent_port || DEFAULT_AGENT_PORT;
		const dialog = buildProgressDialog(frm);

		dialog.show();
		runSigningPipeline(frm, info, port, dialog).catch((err) => {
			dialog.set_state("error", formatError(err));
			console.error("[e_sign] signing failed:", err);
		});
	}

	async function runSigningPipeline(frm, info, port, dialog) {
		// 1) Make sure the local agent is alive and reachable
		dialog.set_state("checking_agent", __("Connecting to local DSC agent…"));
		const agentStatus = await pingAgent(port);
		if (!agentStatus) {
			throw new Error(
				`Cannot reach the dsc-bridge agent at https://${AGENT_HOST}:${port}. ` +
					`Is it running on this machine? See the system tray for the DSC Bridge icon.`
			);
		}
		if (!agentStatus.tokens_detected || !agentStatus.tokens_detected.length) {
			throw new Error(
				__("No USB DSC token detected by the agent. Plug it in and try again.")
			);
		}

		// 2) Ask the server to render the PDF and compute the hash
		dialog.set_state("preparing", __("Preparing PDF and computing document hash…"));
		const initiated = await callServer(INITIATE_API, {
			doctype: frm.doctype,
			docname: frm.doc.name,
		});

		// 3) Hand the hash to the local agent to sign
		dialog.set_state(
			"awaiting_pin",
			__("Waiting for PIN entry on your USB token…") +
				`<br/><small class='text-muted'>${__(
					"The token vendor's PIN dialog should appear shortly."
				)}</small>`
		);
		const signed = await callAgent(port, initiated);

		// 4) Hand the signature back to the server for injection + verification
		dialog.set_state("finalising", __("Injecting signature and verifying PDF…"));
		const finalized = await callServer(FINALIZE_API, {
			session_id: initiated.session_id,
			signature_bytes_b64: signed.signature_bytes_b64,
			cert_der_b64: signed.cert_der_b64,
			cert_chain_der_b64: JSON.stringify(signed.cert_chain_der_b64 || []),
			ocsp_der_b64: signed.ocsp_der_b64 || null,
		});

		dialog.set_state(
			"done",
			__("Document signed successfully.") +
				`<br/><a href="${finalized.file_url}" target="_blank">${__(
					"Download signed PDF"
				)}</a>`
		);

		// Refresh the form so the new attachment + timeline entry show up
		setTimeout(() => frm.reload_doc(), 1500);
	}

	// ============================================================
	//                    AGENT + SERVER PLUMBING
	// ============================================================

	async function pingAgent(port) {
		try {
			const resp = await fetch(`https://${AGENT_HOST}:${port}/v1/status`, {
				method: "GET",
				mode: "cors",
			});
			if (!resp.ok) return null;
			return await resp.json();
		} catch (e) {
			return null;
		}
	}

	async function callAgent(port, initiated) {
		const resp = await fetch(`https://${AGENT_HOST}:${port}/v1/sign`, {
			method: "POST",
			mode: "cors",
			headers: {
				"Content-Type": "application/json",
				"X-DSC-Site-Token": getSiteToken(),
			},
			body: JSON.stringify({
				session_id: initiated.session_id,
				hash_to_sign: initiated.hash_to_sign,
				hash_algorithm: initiated.hash_algorithm,
				expected_fingerprint: initiated.expected_cert_fingerprint,
			}),
		});

		const body = await resp.json();
		if (!resp.ok) {
			throw new Error(
				`${body.error || "AGENT_ERROR"}: ${body.message || resp.statusText}`
			);
		}
		return body;
	}

	function callServer(method, args) {
		return new Promise((resolve, reject) => {
			frappe.call({
				method,
				args,
				callback(r) {
					if (r && r.message) resolve(r.message);
					else reject(new Error(__("Empty response from server")));
				},
				error(err) {
					reject(err);
				},
			});
		});
	}

	function getSiteToken() {
		// The agent stores its per-site token in the OS keychain after pairing.
		// The browser doesn't have direct access, but we send the site URL so
		// the agent can look it up. For initial flows we send empty and rely on
		// the agent's Origin-based check.
		return window.localStorage.getItem("dsc_site_token") || "";
	}

	// ============================================================
	//                     PROGRESS DIALOG
	// ============================================================

	function buildProgressDialog(frm) {
		const STATES = [
			{ key: "checking_agent", label: __("Contacting agent") },
			{ key: "preparing", label: __("Preparing PDF") },
			{ key: "awaiting_pin", label: __("Waiting for PIN") },
			{ key: "finalising", label: __("Finalising signature") },
			{ key: "done", label: __("Done") },
		];

		const dlg = new frappe.ui.Dialog({
			title: __("Sign with DSC: {0} {1}", [frm.doctype, frm.doc.name]),
			size: "small",
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "progress_html",
					options: renderSteps(STATES, null),
				},
				{
					fieldtype: "HTML",
					fieldname: "message_html",
					options: `<div class='dsc-message text-muted'>${__(
						"Starting…"
					)}</div>`,
				},
			],
		});

		dlg.set_state = function (key, message) {
			dlg.fields_dict.progress_html.$wrapper.html(renderSteps(STATES, key));
			let cls = "text-muted";
			if (key === "done") cls = "text-success";
			else if (key === "error") cls = "text-danger";
			else if (key === "awaiting_pin") cls = "text-warning";
			dlg.fields_dict.message_html.$wrapper.html(
				`<div class='dsc-message ${cls}'>${message || ""}</div>`
			);
			if (key === "done" || key === "error") {
				dlg.set_primary_action(__("Close"), () => dlg.hide());
			}
		};

		return dlg;
	}

	function renderSteps(states, current) {
		const idx = states.findIndex((s) => s.key === current);
		const cells = states
			.map((s, i) => {
				let cls = "step-pending";
				if (i < idx) cls = "step-done";
				if (i === idx) cls = "step-active";
				return `<li class="${cls}">${s.label}</li>`;
			})
			.join("");
		return `<ol class='dsc-steps'>${cells}</ol>`;
	}

	// ============================================================
	//                    HISTORY + RETRY HELPERS
	// ============================================================

	function openHistoryDialog(frm, info) {
		const requests = info.signing_requests || [];
		const rows = requests
			.map(
				(r) => `
			<tr>
				<td><a href='/app/dsc-signing-request/${r.name}'>${r.name}</a></td>
				<td><span class='indicator ${indicatorFor(r.status)}'>${r.status}</span></td>
				<td>${r.profile || ""}</td>
				<td>${r.expected_signer_user || ""}</td>
				<td>${r.signed_on || "—"}</td>
				<td>${
					r.signed_file
						? `<a href='/app/file/${r.signed_file}' target='_blank'>📎 PDF</a>`
						: "—"
				}</td>
			</tr>`
			)
			.join("");

		new frappe.ui.Dialog({
			title: __("Signing History"),
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					options: `
						<table class='table table-bordered'>
							<thead>
								<tr><th>Request</th><th>Status</th><th>Profile</th>
									<th>Signer</th><th>Signed On</th><th>File</th></tr>
							</thead>
							<tbody>${rows || `<tr><td colspan='6'>${__("No signing requests")}</td></tr>`}</tbody>
						</table>`,
				},
			],
		}).show();
	}

	function indicatorFor(status) {
		return (
			{
				Pending: "orange",
				"In Progress": "blue",
				Signed: "green",
				Failed: "red",
				Cancelled: "grey",
			}[status] || "grey"
		);
	}

	function retryLastFailed(frm, failed) {
		const target = failed[0];
		frappe.confirm(__("Retry signing request {0}?", [target.name]), () => {
			frappe.call({
				method: RETRY_API,
				args: { signing_request: target.name },
				callback() {
					frappe.show_alert(
						{ message: __("Reset to Pending"), indicator: "blue" },
						5
					);
					frm.reload_doc();
				},
			});
		});
	}

	function formatError(err) {
		const msg = err && err.message ? err.message : String(err);
		return `<strong>${__("Signing failed")}</strong><br/>${frappe.utils.escape_html(msg)}`;
	}
})();
