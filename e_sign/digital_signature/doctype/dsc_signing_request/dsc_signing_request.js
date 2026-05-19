// Shortcut from the signing request to the source document.
//
// The actual "Sign with DSC" button lives on the source DocType (Sales
// Invoice etc.) — that is where the signer has the document context.
// Without this script, signers have to open the request, find the
// source_doctype / source_name fields, and click into the link.
// This adds a one-click "Sign Now" button directly on the request.

frappe.ui.form.on("DSC Signing Request", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (!frm.doc.source_doctype || !frm.doc.source_name) return;

		// Active signing state → big blue "Sign Now" CTA.
		// Terminal state (Signed/Failed/Cancelled) → neutral "Open Source Document"
		// for audit review. Same destination, different intent — only one shown
		// at a time so the action is unambiguous.
		const isActive = frm.doc.status === "Pending" || frm.doc.status === "In Progress";
		const label = isActive ? __("Sign Now") : __("Open Source Document");
		const $btn = frm.add_custom_button(label, () => {
			frappe.set_route("Form", frm.doc.source_doctype, frm.doc.source_name);
		});
		if (isActive) {
			$btn.removeClass("btn-default").addClass("btn-primary");
		}

		if (frm.doc.signed_file) {
			frm.add_custom_button(__("Download Signed PDF"), () => {
				window.open(`/app/file/${frm.doc.signed_file}`, "_blank");
			});
		}
	},
});
