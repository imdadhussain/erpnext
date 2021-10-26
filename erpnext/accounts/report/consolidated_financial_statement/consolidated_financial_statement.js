// Copyright (c) 2016, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Consolidated Financial Statement"] = {
	"filters": [
		{
			"fieldname":"company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
			"reqd": 1
		},
		{
			"fieldname": "from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"default": frappe.defaults.get_user_default("year_start_date"),
			"reqd": 1
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.defaults.get_user_default("year_end_date"),
			"reqd": 1
		},
		{
			"fieldname": "periodicity",
			"label": __("Periodicity"),
			"fieldtype": "Select",
			"options": [
				{ "value": "Custom", "label": __("Custom Date Range") },
				{ "value": "Monthly", "label": __("Monthly") },
				{ "value": "Quarterly", "label": __("Quarterly") },
				{ "value": "Half-Yearly", "label": __("Half-Yearly") },
				{ "value": "Yearly", "label": __("Yearly") }
			],
			"default": "Yearly",
			"reqd": 1
		},
		{
			"fieldname":"finance_book",
			"label": __("Finance Book"),
			"fieldtype": "Link",
			"options": "Finance Book"
		},
		{
			"fieldname":"report",
			"label": __("Report"),
			"fieldtype": "Select",
			"options": ["Profit and Loss Statement", "Balance Sheet", "Cash Flow"],
			"default": "Balance Sheet",
			"reqd": 1
		},
		{
			"fieldname": "presentation_currency",
			"label": __("Currency"),
			"fieldtype": "Select",
			"options": erpnext.get_presentation_currency_list(),
			"default": frappe.defaults.get_user_default("Currency")
		},
		{
			"fieldname":"accumulated_in_group_company",
			"label": __("Accumulated Values in Group Company"),
			"fieldtype": "Check",
			"default": 0
		},
		{
			"fieldname": "include_default_book_entries",
			"label": __("Include Default Book Entries"),
			"fieldtype": "Check",
			"default": 1
		},
		{
			"fieldname":"company_a",
			"label": __("To Company"),
			"fieldtype": "Link",
			"options": "Company",
			"hidden": 1,
			"reqd": 1
		},
		{
			"fieldname":"compare_with_company",
			"label": __("Compare Statements"),
			"fieldtype": "Check",
			"default": 0,
			on_change: () => {
				var compare_with_company = frappe.query_report.get_filter_value('compare_with_company');
				console.log("WITH COMPANY")
				console.log(compare_with_company)
				if (compare_with_company) {
						frappe.query_report.set_filter_value('with_company', "hidden", 0);
					};
					frappe.query_report.refresh();
			},

		},
		{
			"fieldname":"company_b",
			"label": __("from Company"),
			"fieldtype": "Link",
			"options": "Company",
			"hidden": 1,
			"reqd": 1
		},
		
	]
}
