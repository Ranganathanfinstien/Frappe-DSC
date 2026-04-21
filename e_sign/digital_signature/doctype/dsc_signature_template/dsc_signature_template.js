// DSC Signature Template — visual coordinate preview.
//
// pyHanko uses PDF point coordinates with the origin at the BOTTOM-LEFT.
// A US-Letter page is 612 × 792 pt. We render a scaled rectangle preview
// so editors can sanity-check stamp placement without needing a real PDF.

(function () {
"use strict";

const PAGE_WIDTH_PT = 612;
const PAGE_HEIGHT_PT = 792;
const PREVIEW_WIDTH_PX = 200; // matches .dsc-coord-preview in e_sign.css
const PREVIEW_HEIGHT_PX = 260;

frappe.ui.form.on("DSC Signature Template", {
	refresh(frm) {
		renderPreview(frm);
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
			// Convert PDF coords (origin bottom-left) to CSS coords (origin top-left)
			const xPx = (f.x / PAGE_WIDTH_PT) * PREVIEW_WIDTH_PX;
			const wPx = ((f.width || 200) / PAGE_WIDTH_PT) * PREVIEW_WIDTH_PX;
			const hPx = ((f.height || 80) / PAGE_HEIGHT_PT) * PREVIEW_HEIGHT_PX;
			// invert Y because PDF Y grows upward but CSS top grows downward
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

})();
