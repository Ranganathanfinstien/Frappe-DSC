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
	const ABORT_API = "e_sign.api.signing.abort_in_progress";

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
		const ctx = { signing_request: null };

		dialog.show();
		runSigningPipeline(frm, info, port, dialog, ctx).catch((err) => {
			dialog.set_state("error", formatError(err));
			console.error("[e_sign] signing failed:", err);
			// Free up the In Progress request so the user can retry without
			// needing the DB reset.
			if (ctx.signing_request) {
				frappe.call({
					method: ABORT_API,
					args: {
						signing_request: ctx.signing_request,
						reason: (err && err.message) ? err.message : "Client error",
					},
					callback: () => frm.reload_doc(),
				});
			}
		});
	}

	async function runSigningPipeline(frm, info, port, dialog, ctx) {
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

		// 1b) Auto-pair the bridge with this Frappe site if it has never been
		// paired here before. Asks the signer once for confirmation, then mints
		// the pairing code on the server and posts it to the bridge — no codes
		// to copy, no system tray to open. Subsequent signs see no pairing UI.
		if (!isAlreadyPaired(agentStatus)) {
			dialog.set_state("checking_agent", __("Pairing this computer with the site…"));
			const ok = await confirmFirstTimePair();
			if (!ok) {
				throw new Error(__(
					"Pairing was declined. This computer must be paired with the site before it can sign documents."
				));
			}
			await autoPairBridge(port);
		}

		// 2a) Capture signer location. Required for legal evidence — server
		// will refuse the request if coordinates are missing (and enforcement
		// is enabled in DSC Settings). Geolocation needs HTTPS in production;
		// localhost is exempt by browser policy.
		dialog.set_state("locating", __("Capturing signer location…"));
		const coords = await captureSignerLocation();

		// 2a-bis) Fetch cert DER from the bridge so the server can build a
		// PAdES-compliant CMS SignedAttrs (signing-cert must be referenced
		// in SignedAttrs before the token signs SignedAttrs hash).
		const certDerB64 = await fetchSignerCertDer(port, agentStatus);

		// 2b) Ask the server to render the PDF and compute the hash
		dialog.set_state("preparing", __("Preparing PDF and computing document hash…"));
		const initiated = await callServer(INITIATE_API, {
			doctype: frm.doctype,
			docname: frm.doc.name,
			cert_der_b64: certDerB64,
			signer_lat: coords.lat,
			signer_lng: coords.lng,
			signer_accuracy_m: coords.accuracy_m,
		});
		// Capture the request name for the failure handler so it can auto-abort
		// if anything below this point throws.
		if (ctx) ctx.signing_request = initiated.signing_request;

		// 3) Prompt the user for their token PIN. The browser captures it and
		// sends to the agent — we cannot rely on the PKCS#11 module to pop a
		// dialog (HyperPKI's module crashes when called with empty PIN).
		const pin = await promptForPIN(dialog);
		if (!pin) {
			throw new Error(__("PIN entry cancelled"));
		}

		// 4) Hand the hash + PIN to the local agent to sign
		dialog.set_state(
			"awaiting_pin",
			__("Signing on token…") +
				`<br/><small class='text-muted'>${__(
					"Do not unplug the token while signing."
				)}</small>`
		);
		const signed = await callAgent(port, initiated, pin);

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

	// Normalises a site URL for comparison ("https://Site.com/" === "https://site.com").
	function normaliseSiteUrl(u) {
		if (!u) return "";
		try {
			const parsed = new URL(u);
			return (parsed.protocol + "//" + parsed.host).toLowerCase();
		} catch (_e) {
			return String(u).replace(/\/+$/, "").toLowerCase();
		}
	}

	// Returns true if the bridge is already paired with this Frappe site.
	function isAlreadyPaired(agentStatus) {
		const here = normaliseSiteUrl(window.location.origin);
		const paired = (agentStatus && agentStatus.paired_sites) || [];
		return paired.some((s) => normaliseSiteUrl(s) === here);
	}

	// Pair the bridge with this Frappe site without showing the user a code.
	// Server mints a one-time code, JS posts it straight to the bridge, bridge
	// stores the resulting site token in the OS keychain. Total user actions: 0.
	async function autoPairBridge(port) {
		const codeResp = await new Promise((resolve, reject) => {
			frappe.call({
				method: "e_sign.api.agent.generate_pairing_code",
				callback: (r) => (r && r.message ? resolve(r.message) : reject(new Error(__("Could not generate a pairing code.")))),
				error: () => reject(new Error(__("Could not generate a pairing code."))),
			});
		});

		const resp = await fetch(`https://${AGENT_HOST}:${port}/v1/pair`, {
			method: "POST",
			mode: "cors",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				pairing_code: codeResp.pairing_code,
				site_url: codeResp.site_url || window.location.origin,
			}),
		});
		if (!resp.ok) {
			let detail = "";
			try { detail = (await resp.json()).message || ""; } catch (_e) {}
			throw new Error(__("Could not pair this computer with the signing site.") + (detail ? " " + detail : ""));
		}
	}

	// Ask the user once before pairing. Most signers will just click "Pair" —
	// this confirmation exists only so we never silently register a machine
	// against a Frappe site without their awareness.
	function confirmFirstTimePair() {
		return new Promise((resolve) => {
			frappe.confirm(
				__(
					"This is the first time signing from this computer. " +
					"Allow it to be paired with this site so signing works automatically from now on?"
				),
				() => resolve(true),
				() => resolve(false)
			);
		});
	}

	function captureSignerLocation() {
		// Wraps navigator.geolocation in a promise. Rejects with a
		// user-readable Error so the signing pipeline aborts cleanly when
		// the signer denies permission, the device has no location service,
		// or we time out waiting for a fix.
		return new Promise((resolve, reject) => {
			if (!("geolocation" in navigator)) {
				reject(new Error(__(
					"This browser does not support location services. " +
					"Digital signing requires a browser that can provide location."
				)));
				return;
			}
			// Browsers block geolocation on plain HTTP (localhost is exempt).
			// On non-secure origins, skip browser capture and let the server
			// decide whether coordinates are mandatory (DSC Settings).
			const proto = window.location.protocol;
			const host = window.location.hostname;
			const isSecure = proto === "https:" || host === "localhost" || host === "127.0.0.1";
			if (!isSecure) {
				resolve({ lat: null, lng: null, accuracy_m: null });
				return;
			}
			navigator.geolocation.getCurrentPosition(
				(pos) => {
					resolve({
						lat: pos.coords.latitude,
						lng: pos.coords.longitude,
						accuracy_m: pos.coords.accuracy,
					});
				},
				(err) => {
					let msg = __("Location access is required to sign documents.");
					if (err && err.code === err.PERMISSION_DENIED) {
						msg = __(
							"Location access was blocked. Open your browser's site settings, " +
							"allow location for this site, then click Sign again."
						);
					} else if (err && err.code === err.POSITION_UNAVAILABLE) {
						msg = __(
							"Your device could not determine its location. " +
							"Enable location services in your operating system and try again."
						);
					} else if (err && err.code === err.TIMEOUT) {
						msg = __(
							"Timed out waiting for location. Move closer to a window or check that " +
							"location services are enabled, then try again."
						);
					}
					reject(new Error(msg));
				},
				{ enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 }
			);
		});
	}

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

	// Asks the bridge for the certificate list on the connected token and
	// returns the DER (base64) of the cert that should be used for signing.
	// We pick the first cert; the server will reject if its fingerprint
	// doesn't match the one on the DSC Profile.
	async function fetchSignerCertDer(port, agentStatus) {
		const resp = await fetch(`https://${AGENT_HOST}:${port}/v1/certs`, {
			method: "GET",
			mode: "cors",
			headers: { "X-DSC-Site-Token": getSiteToken() },
		});
		if (!resp.ok) {
			throw new Error(__("Could not read certificate from the token."));
		}
		const body = await resp.json();
		const certs = (body && body.certs) || [];
		if (!certs.length) {
			throw new Error(__("No certificate found on the token."));
		}
		const cert = certs[0];
		if (!cert.cert_der_b64) {
			throw new Error(__(
				"The DSC Bridge on this machine is too old — please update it to receive the cert DER."
			));
		}
		return cert.cert_der_b64;
	}

	async function callAgent(port, initiated, pin) {
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
				// HMAC + replay protection (PRD §13.4 / §17.1) — server signs
				// the payload with the shared HMAC secret; the bridge verifies
				// it before performing any token operation.
				timestamp: initiated.timestamp,
				nonce: initiated.nonce,
				hmac: initiated.hmac,
				pin,
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

	function promptForPIN(progressDialog) {
		// Hide the progress dialog while we collect the PIN, then re-show.
		progressDialog.hide();
		return new Promise((resolve) => {
			const dlg = new frappe.ui.Dialog({
				title: __("Enter Token PIN"),
				fields: [
					{
						fieldtype: "Password",
						fieldname: "pin",
						label: __("DSC Token PIN"),
						reqd: 1,
					},
				],
				primary_action_label: __("Sign"),
				primary_action(values) {
					dlg.hide();
					progressDialog.show();
					resolve(values.pin);
				},
				secondary_action_label: __("Cancel"),
				secondary_action() {
					dlg.hide();
					progressDialog.show();
					resolve(null);
				},
			});
			dlg.show();
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
			{ key: "locating", label: __("Capturing location") },
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
