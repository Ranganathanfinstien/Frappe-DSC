frappe.query_reports["DSC Failure Reasons"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "source_doctype",
			label: __("Source DocType"),
			fieldtype: "Link",
			options: "DocType",
		},
	],
};
