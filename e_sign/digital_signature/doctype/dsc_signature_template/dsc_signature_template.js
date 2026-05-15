// DSC Signature Template — visual coordinate preview + drag-drop designer.
//
// pyHanko uses PDF point coordinates with the origin at the BOTTOM-LEFT.
// A US-Letter page is 612 × 792 pt. The form shows:
//   1. A small read-only preview of current coords (the original behaviour)
//   2. An "Open Designer" button that opens a modal canvas where users can
//      drag/resize signature rectangles onto a representation of the page,
//      with optional rendering of a real reference PDF via PDF.js.

(function () {
"use strict";

const PAGE_WIDTH_PT = 612;
const PAGE_HEIGHT_PT = 792;
const PREVIEW_WIDTH_PX = 200; // matches .dsc-coord-preview in e_sign.css
const PREVIEW_HEIGHT_PX = 260;
const DESIGNER_WIDTH_PX = 600;
const DESIGNER_HEIGHT_PX = (DESIGNER_WIDTH_PX * PAGE_HEIGHT_PT) / PAGE_WIDTH_PT;

frappe.ui.form.on("DSC Signature Template", {
	refresh(frm) {
		renderPreview(frm);
		addDesignerButton(frm);
	},
	fields_add(frm) {
		renderPreview(frm);
	},
	fields_remove(frm) {
		renderPreview(frm);
	},
});

frappe.ui.form.on("DSC Signature Field", {
	x: renderRow,
	y: renderRow,
	width: renderRow,
	height: renderRow,
	page_number: renderRow,
});

function renderRow(frm) {
	renderPreview(frm);
}

function renderPreview(frm) {
	if (!frm.fields_dict.fields) return;

	const wrapper = frm.fields_dict.fields.$wrapper;
	wrapper.find(".dsc-preview-host").remove();

	const rows = (frm.doc.fields || []).filter(
		(f) => f.x !== undefined && f.y !== undefined
	);
	if (!rows.length) return;

	const stamps = rows
		.map((f) => {
			const xPx = (f.x / PAGE_WIDTH_PT) * PREVIEW_WIDTH_PX;
			const wPx = ((f.width || 200) / PAGE_WIDTH_PT) * PREVIEW_WIDTH_PX;
			const hPx = ((f.height || 80) / PAGE_HEIGHT_PT) * PREVIEW_HEIGHT_PX;
			const yPx =
				PREVIEW_HEIGHT_PX -
				((f.y + (f.height || 80)) / PAGE_HEIGHT_PT) * PREVIEW_HEIGHT_PX;

			const offPage = f.x + (f.width || 0) > PAGE_WIDTH_PT || f.y + (f.height || 0) > PAGE_HEIGHT_PT;
			const colour = offPage ? "rgba(244,67,54,0.35)" : "rgba(33,150,243,0.25)";
			const border = offPage ? "#d32f2f" : "#1976d2";

			return `<div class='stamp' style='
				left:${xPx}px; top:${yPx}px;
				width:${wPx}px; height:${hPx}px;
				background:${colour}; border-color:${border}'
				title='page ${f.page_number || 1}, x=${f.x}, y=${f.y}'>
				${frappe.utils.escape_html(f.field_name || "")}
			</div>`;
		})
		.join("");

	const offPageCount = rows.filter(
		(f) => f.x + (f.width || 0) > PAGE_WIDTH_PT || f.y + (f.height || 0) > PAGE_HEIGHT_PT
	).length;
	const warning = offPageCount
		? `<div class='text-danger' style='font-size:11px'>${__(
				"⚠ {0} field(s) extend off the page (612×792 Letter).",
				[offPageCount]
		  )}</div>`
		: "";

	wrapper.append(`
		<div class='dsc-preview-host' style='margin-top:10px'>
			<small class='text-muted'>${__("Placement preview (US Letter, 612×792 pt)")}:</small>
			<div class='dsc-coord-preview'>${stamps}</div>
			${warning}
		</div>
	`);
}

function addDesignerButton(frm) {
	frm.add_custom_button(__("Open Designer"), () => openDesigner(frm), __("Layout"));
}

function openDesigner(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Signature Field Designer"),
		size: "extra-large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "designer_html",
			},
		],
		primary_action_label: __("Save & Close"),
		primary_action() {
			persistFields(frm, dialog);
			dialog.hide();
			frm.refresh();
		},
	});

	dialog.show();
	const $body = dialog.fields_dict.designer_html.$wrapper;
	$body.html(designerMarkup());

	const ctx = {
		frm,
		dialog,
		$body,
		canvas: $body.find(".dsc-designer-canvas")[0],
		fields: deepCloneFields(frm.doc.fields || []),
		page: 1,
		dragState: null,
	};

	// Stash the live state on the dialog so primary_action can read it back.
	dialog.__dsc_ctx = ctx;

	wireDesigner(ctx);
	renderDesignerFields(ctx);
}

function designerMarkup() {
	return `
	<div class='dsc-designer-host'>
		<div class='dsc-designer-toolbar' style='margin-bottom:10px; display:flex; gap:8px; align-items:center; flex-wrap:wrap;'>
			<button class='btn btn-default btn-sm dsc-add-field'>
				+ ${__("Add Field")}
			</button>
			<label style='margin:0; display:flex; gap:6px; align-items:center;'>
				<span>${__("Page")}</span>
				<input type='number' min='1' value='1' class='form-control input-xs dsc-page-num' style='width:60px'>
			</label>
			<label style='margin:0; display:flex; gap:6px; align-items:center;'>
				<span>${__("Reference PDF")}</span>
				<input type='file' accept='application/pdf' class='dsc-ref-pdf'>
			</label>
			<small class='text-muted'>
				${__("Drag to move · drag corner to resize · click to select · Del to remove")}
			</small>
		</div>
		<div class='dsc-designer-canvas-wrap' style='position:relative; display:inline-block; border:1px solid #ddd; background:#f8f9fa;'>
			<canvas class='dsc-designer-pdf' width='${DESIGNER_WIDTH_PX}' height='${DESIGNER_HEIGHT_PX}'
				style='display:block; background:white;'></canvas>
			<div class='dsc-designer-canvas' tabindex='0' style='
				position:absolute; left:0; top:0;
				width:${DESIGNER_WIDTH_PX}px; height:${DESIGNER_HEIGHT_PX}px;
				outline:none;
			'></div>
		</div>
		<div class='dsc-designer-coords' style='margin-top:8px; font-size:11px; color:#666;'>
			${__("US Letter (612×792 pt) · origin bottom-left")}
		</div>
	</div>`;
}

function wireDesigner(ctx) {
	const { $body } = ctx;

	$body.find(".dsc-add-field").on("click", () => {
		const newField = {
			field_name: `field_${(ctx.fields.length + 1)}`,
			page_number: ctx.page,
			x: 100,
			y: 100,
			width: 200,
			height: 80,
			assigned_profile: null,
			__id: frappe.utils.get_random(8),
		};
		ctx.fields.push(newField);
		renderDesignerFields(ctx);
	});

	$body.find(".dsc-page-num").on("change", function () {
		ctx.page = parseInt(this.value, 10) || 1;
		renderDesignerFields(ctx);
	});

	$body.find(".dsc-ref-pdf").on("change", function () {
		const file = this.files && this.files[0];
		if (!file) return;
		renderReferencePDF(ctx, file);
	});

	$(ctx.canvas).on("keydown", (e) => {
		if (e.key === "Delete" || e.key === "Backspace") {
			const sel = ctx.fields.find((f) => f.__selected);
			if (sel) {
				ctx.fields = ctx.fields.filter((f) => f !== sel);
				renderDesignerFields(ctx);
			}
		}
	});

	$(ctx.canvas).on("mousedown", (e) => {
		if (e.target === ctx.canvas) {
			ctx.fields.forEach((f) => (f.__selected = false));
			renderDesignerFields(ctx);
		}
	});
}

function renderDesignerFields(ctx) {
	const $canvas = $(ctx.canvas);
	$canvas.empty();
	const scale = DESIGNER_WIDTH_PX / PAGE_WIDTH_PT;

	ctx.fields
		.filter((f) => (f.page_number || 1) === ctx.page)
		.forEach((f) => {
			const xPx = (f.x || 0) * scale;
			const wPx = (f.width || 200) * scale;
			const hPx = (f.height || 80) * scale;
			// Y inversion: PDF origin bottom-left → CSS top-left
			const yPx =
				DESIGNER_HEIGHT_PX -
				((f.y || 0) + (f.height || 80)) * scale;

			const $rect = $(`
				<div class='dsc-design-field' style='
					position:absolute;
					left:${xPx}px; top:${yPx}px;
					width:${wPx}px; height:${hPx}px;
					border:2px solid ${f.__selected ? "#d32f2f" : "#1976d2"};
					background: rgba(33,150,243,${f.__selected ? "0.35" : "0.18"});
					cursor:move;
					box-sizing:border-box;
					user-select:none;
				'>
					<div class='dsc-design-label' style='font-size:10px; padding:2px; color:#000;'>
						${frappe.utils.escape_html(f.field_name || "")}
					</div>
					<div class='dsc-resize-handle' style='
						position:absolute; right:-4px; bottom:-4px;
						width:10px; height:10px;
						background:#1976d2; cursor:nwse-resize;
					'></div>
				</div>
			`);

			$rect.on("mousedown", (e) => {
				if ($(e.target).hasClass("dsc-resize-handle")) {
					beginResize(ctx, f, e);
				} else {
					beginDrag(ctx, f, e);
				}
			});

			$canvas.append($rect);
		});

	updateCoordReadout(ctx);
}

function beginDrag(ctx, field, e) {
	e.preventDefault();
	e.stopPropagation();
	ctx.fields.forEach((f) => (f.__selected = false));
	field.__selected = true;

	const startX = e.clientX;
	const startY = e.clientY;
	const origX = field.x;
	const origY = field.y;
	const scale = DESIGNER_WIDTH_PX / PAGE_WIDTH_PT;

	const move = (ev) => {
		const dxPx = ev.clientX - startX;
		const dyPx = ev.clientY - startY;
		const dxPt = dxPx / scale;
		const dyPt = dyPx / scale;
		// PDF Y grows upward, CSS Y grows downward — invert dy
		field.x = Math.max(0, Math.round(origX + dxPt));
		field.y = Math.max(0, Math.round(origY - dyPt));
		renderDesignerFields(ctx);
	};
	const up = () => {
		document.removeEventListener("mousemove", move);
		document.removeEventListener("mouseup", up);
	};
	document.addEventListener("mousemove", move);
	document.addEventListener("mouseup", up);
}

function beginResize(ctx, field, e) {
	e.preventDefault();
	e.stopPropagation();
	ctx.fields.forEach((f) => (f.__selected = false));
	field.__selected = true;

	const startX = e.clientX;
	const startY = e.clientY;
	const origW = field.width || 200;
	const origH = field.height || 80;
	const origY = field.y;
	const scale = DESIGNER_WIDTH_PX / PAGE_WIDTH_PT;

	const move = (ev) => {
		const dxPx = ev.clientX - startX;
		const dyPx = ev.clientY - startY;
		const dxPt = dxPx / scale;
		const dyPt = dyPx / scale;
		field.width = Math.max(20, Math.round(origW + dxPt));
		field.height = Math.max(20, Math.round(origH + dyPt));
		// when resizing from bottom-right, PDF y stays anchored to original (since
		// PDF y is bottom-left of rect, growing height pushes top edge up — but the
		// stored y is the bottom-left, so we lower y by the height delta for visual
		// stability with the CSS top-left anchor)
		field.y = Math.max(0, Math.round(origY - dyPt));
		renderDesignerFields(ctx);
	};
	const up = () => {
		document.removeEventListener("mousemove", move);
		document.removeEventListener("mouseup", up);
	};
	document.addEventListener("mousemove", move);
	document.addEventListener("mouseup", up);
}

function updateCoordReadout(ctx) {
	const sel = ctx.fields.find((f) => f.__selected);
	const $readout = ctx.$body.find(".dsc-designer-coords");
	if (!sel) {
		$readout.text(__("US Letter (612×792 pt) · origin bottom-left"));
		return;
	}
	$readout.text(
		`${sel.field_name}: page ${sel.page_number || 1} · x=${sel.x} y=${sel.y} w=${sel.width} h=${sel.height}`
	);
}

function deepCloneFields(rows) {
	return (rows || []).map((r, i) => ({
		field_name: r.field_name || `field_${i + 1}`,
		page_number: r.page_number || 1,
		x: r.x || 0,
		y: r.y || 0,
		width: r.width || 200,
		height: r.height || 80,
		assigned_profile: r.assigned_profile || null,
		__id: r.name || frappe.utils.get_random(8),
	}));
}

function persistFields(frm, dialog) {
	const ctx = dialog.__dsc_ctx;
	if (!ctx) return;
	frm.clear_table("fields");
	(ctx.fields || []).forEach((f) => {
		frm.add_child("fields", {
			field_name: f.field_name,
			page_number: f.page_number,
			x: f.x,
			y: f.y,
			width: f.width,
			height: f.height,
			assigned_profile: f.assigned_profile || null,
		});
	});
	frm.refresh_field("fields");
}

function renderReferencePDF(ctx, file) {
	const reader = new FileReader();
	reader.onload = function () {
		const typedArray = new Uint8Array(this.result);
		// Use Frappe's bundled PDF.js if available; fall back to dynamic import.
		const pdfjsLib = window["pdfjs-dist/build/pdf"] || window.pdfjsLib;
		if (!pdfjsLib) {
			frappe.msgprint(__(
				"PDF.js is not loaded in this Frappe build. Designer canvas remains blank — drag/drop still works."
			));
			return;
		}
		pdfjsLib.GlobalWorkerOptions.workerSrc =
			"https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
		pdfjsLib.getDocument({ data: typedArray }).promise.then((pdf) => {
			pdf.getPage(ctx.page || 1).then((page) => {
				const viewport = page.getViewport({
					scale: DESIGNER_WIDTH_PX / page.getViewport({ scale: 1 }).width,
				});
				const $pdfCanvas = ctx.$body.find(".dsc-designer-pdf")[0];
				const renderCtx = $pdfCanvas.getContext("2d");
				$pdfCanvas.width = viewport.width;
				$pdfCanvas.height = viewport.height;
				page.render({ canvasContext: renderCtx, viewport });
			});
		}).catch((err) => {
			frappe.msgprint(__("Failed to render PDF: ") + err.message);
		});
	};
	reader.readAsArrayBuffer(file);
}

})();
