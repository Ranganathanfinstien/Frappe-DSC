frappe.query_reports["DSC Sign Volume"] = {
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
			fieldname: "profile",
			label: __("Profile"),
			fieldtype: "Link",
			options: "DSC Profile",
		},
		{
			fieldname: "source_doctype",
			label: __("Source DocType"),
			fieldtype: "Link",
			options: "DocType",
		},
	],
};
