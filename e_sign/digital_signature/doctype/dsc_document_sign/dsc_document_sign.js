/**
 * DSC Document Sign — interactive signature placement.
 *
 * Renders the uploaded PDF with pdf.js and lets the signer drag a box onto
 * the page to choose where the digital signature stamp will appear. The box
 * position is converted from on-screen pixels into PDF points (origin at the
 * bottom-left, the coordinate space pyHanko expects) and written into the
 * read-only sig_* fields.
 *
 * The signing itself is handled by the global e_sign.js "Sign with DSC"
 * button, which appears once saving this record has created a pending
 * DSC Signing Request.
 */

frappe.ui.form.on("DSC Document Sign", {
	refresh(frm) {
		render_viewer(frm);

		if (frm.doc.signed_file) {
			frm.add_custom_button(__("Open Signed PDF"), () => {
				window.open("/app/file/" + encodeURIComponent(frm.doc.signed_file), "_blank");
			});
		}

		if (frm.doc.status === "Draft" && !frm.is_new()) {
			frm.dashboard.set_headline_alert(
				`<span class="indicator orange">${__(
					"Place the signature box, then Save — the Sign with DSC button appears next."
				)}</span>`
			);
		}
	},

	uploaded_pdf(frm) {
		// Re-render whenever a different PDF is attached.
		render_viewer(frm);
	},
});

// pdf.js is vendored into the app (e_sign/public/js/vendor/) and served from
// /assets/ so signature placement works fully offline — no CDN, no internet.
const PDFJS_URL = "/assets/e_sign/js/vendor/pdf.min.js";
const PDFJS_WORKER = "/assets/e_sign/js/vendor/pdf.worker.min.js";

// Load pdf.js once per browser session.
function load_pdfjs() {
	if (window.pdfjsLib) return Promise.resolve(window.pdfjsLib);
	if (window._dsc_pdfjs_promise) return window._dsc_pdfjs_promise;

	window._dsc_pdfjs_promise = new Promise((resolve, reject) => {
		const s = document.createElement("script");
		s.src = PDFJS_URL;
		s.onload = () => {
			if (window.pdfjsLib) {
				window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
				resolve(window.pdfjsLib);
			} else {
				reject(new Error(__("pdf.js failed to initialise.")));
			}
		};
		s.onerror = () => reject(new Error(__("Could not load the PDF viewer (pdf.js).")));
		document.head.appendChild(s);
	});
	return window._dsc_pdfjs_promise;
}

function render_viewer(frm) {
	const field = frm.get_field("placement_viewer");
	if (!field || !field.$wrapper) return;

	const $w = field.$wrapper;
	$w.empty();

	if (!frm.doc.uploaded_pdf) {
		$w.html(
			`<div class="text-muted" style="padding:16px">${__(
				"Upload a PDF in the field above, then come back here to place your signature."
			)}</div>`
		);
		return;
	}

	if (frm.doc.status === "Signed") {
		$w.html(
			`<div class="indicator green" style="padding:12px">${__(
				"This document has been signed."
			)}</div>`
		);
		return;
	}

	// The box is only movable while the record is still a Draft. Once a
	// signing request exists the placement is locked.
	const editable = !frm.doc.status || frm.doc.status === "Draft";

	const $host = $('<div class="dsc-doc-sign-viewer"></div>').appendTo($w);
	$host.html(`<div class="text-muted" style="padding:12px">${__("Loading PDF…")}</div>`);

	load_pdfjs()
		.then((pdfjsLib) => init_viewer(frm, pdfjsLib, $host, editable))
		.catch((err) => {
			$host.html(
				`<div class="text-danger" style="padding:12px">${frappe.utils.escape_html(
					(err && err.message) || String(err)
				)}</div>`
			);
		});
}

async function init_viewer(frm, pdfjsLib, $host, editable) {
	// Drop any drag handlers left over from a previous render.
	$(document).off(".dscbox");

	const buf = await fetch(frm.doc.uploaded_pdf, { credentials: "include" }).then((r) => {
		if (!r.ok) throw new Error(__("Could not load the uploaded PDF."));
		return r.arrayBuffer();
	});
	const pdf = await pdfjsLib.getDocument({ data: buf }).promise;

	const state = {
		pdf,
		pageNum: Math.min(Math.max(frm.doc.sig_page || 1, 1), pdf.numPages),
		scale: 1,
		viewport: null,
	};

	$host.empty();

	const $toolbar = $(`
		<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap">
			<button class="btn btn-xs btn-default dsc-prev">&lsaquo; ${__("Prev")}</button>
			<span class="dsc-pageinfo text-muted"></span>
			<button class="btn btn-xs btn-default dsc-next">${__("Next")} &rsaquo;</button>
			<span class="text-muted" style="margin-left:auto">${
				editable
					? __("Drag the blue box to position your signature; drag the corner to resize.")
					: __("Signature placement (locked).")
			}</span>
		</div>`).appendTo($host);

	const $stage = $(
		'<div class="dsc-stage" style="position:relative;display:inline-block;' +
			'border:1px solid var(--border-color);max-width:100%;line-height:0"></div>'
	).appendTo($host);
	const $canvas = $('<canvas style="display:block"></canvas>').appendTo($stage);

	const $box = $('<div class="dsc-sig-box"></div>').appendTo($stage);
	$box.css({
		position: "absolute",
		border: "2px solid #2490ef",
		background: "rgba(36,144,239,0.15)",
		cursor: editable ? "move" : "default",
		"box-sizing": "border-box",
	});
	const $label = $(
		`<div style="font-size:10px;color:#2490ef;padding:1px 3px;line-height:1.2">${__(
			"Signature"
		)}</div>`
	).appendTo($box);
	$label.css({ "pointer-events": "none" });

	const $handle = $('<div class="dsc-sig-handle"></div>').appendTo($box);
	$handle.css({
		position: "absolute",
		right: "-7px",
		bottom: "-7px",
		width: "14px",
		height: "14px",
		background: "#2490ef",
		border: "2px solid #fff",
		"border-radius": "50%",
		cursor: editable ? "nwse-resize" : "default",
		display: editable ? "block" : "none",
	});

	const round2 = (n) => Math.round(n * 100) / 100;

	async function renderPage() {
		const page = await state.pdf.getPage(state.pageNum);
		const unscaled = page.getViewport({ scale: 1 });
		// Fit the page to the width actually available in the form field. The
		// canvas must render at its true pixel size — if CSS were to shrink it,
		// the absolutely-positioned signature box would desync from the page
		// and land below it. Subtract a few px for the stage border; never
		// upscale past 1.5×.
		const avail = Math.max(($host.width() || 640) - 6, 280);
		state.scale = Math.min(avail / unscaled.width, 1.5);
		const viewport = page.getViewport({ scale: state.scale });
		state.viewport = viewport;

		const canvas = $canvas[0];
		canvas.width = viewport.width;
		canvas.height = viewport.height;
		await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;

		$toolbar
			.find(".dsc-pageinfo")
			.text(__("Page {0} of {1}", [state.pageNum, state.pdf.numPages]));
		positionBoxFromDoc();
	}

	function positionBoxFromDoc() {
		const vp = state.viewport;
		const s = state.scale;
		const w = (frm.doc.sig_width || 200) * s;
		const h = (frm.doc.sig_height || 80) * s;

		let left;
		let top;
		if (frm.doc.sig_width && frm.doc.sig_page === state.pageNum) {
			// Re-show a placement the signer already made on this page.
			left = (frm.doc.sig_x || 0) * s;
			top = vp.height - (frm.doc.sig_y || 0) * s - h;
		} else {
			// Default: lower-right corner with a small margin.
			left = vp.width - w - 24;
			top = vp.height - h - 24;
		}
		left = Math.max(0, Math.min(left, vp.width - w));
		top = Math.max(0, Math.min(top, vp.height - h));
		$box.css({ left: left + "px", top: top + "px", width: w + "px", height: h + "px" });
	}

	function commitBox() {
		if (!editable) return;
		const vp = state.viewport;
		const s = state.scale;
		const left = parseFloat($box.css("left"));
		const top = parseFloat($box.css("top"));
		const w = parseFloat($box.css("width"));
		const h = parseFloat($box.css("height"));

		// Canvas y grows downward; PDF y grows upward from the bottom edge.
		frm.set_value("sig_page", state.pageNum);
		frm.set_value("sig_x", round2(left / s));
		frm.set_value("sig_y", round2((vp.height - top - h) / s));
		frm.set_value("sig_width", round2(w / s));
		frm.set_value("sig_height", round2(h / s));
	}

	if (editable) {
		let mode = null;
		let startX;
		let startY;
		let orig;

		$box.on("mousedown", (e) => {
			mode = $(e.target).hasClass("dsc-sig-handle") ? "resize" : "move";
			startX = e.pageX;
			startY = e.pageY;
			orig = {
				left: parseFloat($box.css("left")),
				top: parseFloat($box.css("top")),
				w: parseFloat($box.css("width")),
				h: parseFloat($box.css("height")),
			};
			e.preventDefault();
		});

		$(document).on("mousemove.dscbox", (e) => {
			if (!mode) return;
			const vp = state.viewport;
			const dx = e.pageX - startX;
			const dy = e.pageY - startY;
			if (mode === "move") {
				const left = Math.max(0, Math.min(orig.left + dx, vp.width - orig.w));
				const top = Math.max(0, Math.min(orig.top + dy, vp.height - orig.h));
				$box.css({ left: left + "px", top: top + "px" });
			} else {
				const w = Math.max(40, Math.min(orig.w + dx, vp.width - orig.left));
				const h = Math.max(20, Math.min(orig.h + dy, vp.height - orig.top));
				$box.css({ width: w + "px", height: h + "px" });
			}
		});

		$(document).on("mouseup.dscbox", () => {
			if (mode) {
				mode = null;
				commitBox();
			}
		});
	}

	$toolbar.find(".dsc-prev").on("click", () => {
		if (state.pageNum > 1) {
			state.pageNum -= 1;
			renderPage().then(() => editable && commitBox());
		}
	});
	$toolbar.find(".dsc-next").on("click", () => {
		if (state.pageNum < state.pdf.numPages) {
			state.pageNum += 1;
			renderPage().then(() => editable && commitBox());
		}
	});

	await renderPage();
}
