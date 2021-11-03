# Copyright (c) 2013, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe, erpnext
from frappe import _
from frappe.utils import flt, cint, getdate
from erpnext.accounts.utils import get_fiscal_year
from erpnext.accounts.report.utils import get_currency, convert_to_presentation_currency
from erpnext.accounts.report.financial_statements import get_fiscal_year_data, sort_accounts,get_period_list
from erpnext.accounts.report.balance_sheet.balance_sheet import (get_provisional_profit_loss,
	check_opening_balance, get_chart_data)
from erpnext.accounts.report.profit_and_loss_statement.profit_and_loss_statement import (get_net_profit_loss,
	get_chart_data as get_pl_chart_data)
from erpnext.accounts.report.cash_flow.cash_flow import (get_cash_flow_accounts, get_account_type_based_gl_data,
	add_total_row_account)

def execute(filters=None):
	columns, data, message, chart = [], [], [], []

	if not filters.get('company'):
		return columns, data, message, chart

	period_list = get_period_list(filters.from_date, filters.to_date,
		filters.periodicity, filters.accumulated_in_group_company, filters.company)

	fiscal_year = get_fiscal_year_data(filters.from_date, filters.to_date)
	# get_fiscal_year_data(filters.get('from_fiscal_year'), filters.get('to_fiscal_year'))


	companies_column, companies = get_companies(filters)
	columns = get_columns(companies_column, filters.periodicity, period_list,filters.accumulated_in_group_company)

	if filters.get('report') == "Balance Sheet":
		data, message, chart = get_balance_sheet_data(period_list, companies, columns, filters)
	elif filters.get('report') == "Profit and Loss Statement":
		data, message, chart = get_profit_loss_data(fiscal_year, companies, columns, filters)
	else:
		if cint(frappe.db.get_single_value('Accounts Settings', 'use_custom_cash_flow')):
			from erpnext.accounts.report.cash_flow.custom_cash_flow import execute as execute_custom
			return execute_custom(filters=filters)

		data = get_cash_flow_data(fiscal_year, companies, filters)

	return columns, data, message, chart

def get_balance_sheet_data(period_list, companies, columns, filters, cost_center_wise=False):

	data = []
	asset = get_data(companies, "Asset", "Debit", period_list, filters=filters, cost_center_wise=cost_center_wise)

	liability = get_data(companies, "Liability", "Credit", period_list, filters=filters, cost_center_wise=cost_center_wise)

	equity = get_data(companies, "Equity", "Credit", period_list, filters=filters, cost_center_wise=cost_center_wise)
	data.extend(asset or [])
	data.extend(liability or [])
	data.extend(equity or [])

	company_currency = get_company_currency(filters)

	provisional_profit_loss, total_credit = get_provisional_profit_loss(asset, liability, equity,
		period_list, filters.get('company'), company_currency, False)
	message, opening_balance = check_opening_balance(asset, liability, equity)

	if opening_balance and round(opening_balance,2) !=0:
		unclosed ={
			"account_name": "'" + _("Unclosed Fiscal Years Profit / Loss (Credit)") + "'",
			"account": "'" + _("Unclosed Fiscal Years Profit / Loss (Credit)") + "'",
			"warn_if_negative": True,
			"currency": company_currency
		}
		# for period in period_list:
		# 	unclosed[period.key] = opening_balance
		# 	if provisional_profit_loss:
		# 		provisional_profit_loss[period.key] = provisional_profit_loss[period.key] - opening_balance
		# unclosed["total"]=opening_balance

		for company in companies:
			unclosed[company] = opening_balance
			if provisional_profit_loss:
				provisional_profit_loss[company] = provisional_profit_loss[company] - opening_balance
		unclosed["total"]=opening_balance
		data.append(unclosed)

	if provisional_profit_loss:
		data.append(provisional_profit_loss)
	if total_credit:
		data.append(total_credit)

	chart = get_chart_data(filters, columns, asset, liability, equity)

	return data, message, chart


def get_profit_loss_data(fiscal_year, companies, columns, filters, cost_center_wise=False):
	income, expense, net_profit_loss = get_income_expense_data(companies, fiscal_year, filters, cost_center_wise=cost_center_wise)

	data = []
	data.extend(income or [])
	data.extend(expense or [])
	if net_profit_loss:
		data.append(net_profit_loss)

	chart = get_pl_chart_data(filters, columns, income, expense, net_profit_loss)

	return data, None, chart

def get_income_expense_data(companies, fiscal_year, filters, cost_center_wise=False):
	company_currency = get_company_currency(filters)
	income = get_data(companies, "Income", "Credit", fiscal_year, filters, ignore_closing_entries=True, cost_center_wise=cost_center_wise)

	expense = get_data(companies, "Expense", "Debit", fiscal_year, filters, ignore_closing_entries=True, cost_center_wise=cost_center_wise)

	net_profit_loss = get_net_profit_loss(income, expense, companies, filters.company, company_currency, True)

	return income, expense, net_profit_loss

def get_cash_flow_data(fiscal_year, companies, filters):
	cash_flow_accounts = get_cash_flow_accounts()

	income, expense, net_profit_loss = get_income_expense_data(companies, fiscal_year, filters)

	data = []
	company_currency = get_company_currency(filters)

	for cash_flow_account in cash_flow_accounts:
		section_data = []
		data.append({
			"account_name": cash_flow_account['section_header'],
			"parent_account": None,
			"indent": 0.0,
			"account": cash_flow_account['section_header']
		})

		if len(data) == 1:
			# add first net income in operations section
			if net_profit_loss:
				net_profit_loss.update({
					"indent": 1,
					"parent_account": cash_flow_accounts[0]['section_header']
				})
				data.append(net_profit_loss)
				section_data.append(net_profit_loss)

		for account in cash_flow_account['account_types']:
			account_data = get_account_type_based_data(account['account_type'], companies, fiscal_year, filters)
			account_data.update({
				"account_name": account['label'],
				"account": account['label'],
				"indent": 1,
				"parent_account": cash_flow_account['section_header'],
				"currency": company_currency
			})
			data.append(account_data)
			section_data.append(account_data)

		add_total_row_account(data, section_data, cash_flow_account['section_footer'],
			companies, company_currency, True)

	add_total_row_account(data, data, _("Net Change in Cash"), companies, company_currency, True)

	return data

def get_account_type_based_data(account_type, companies, fiscal_year, filters):
	data = {}
	total = 0
	for company in companies:
		amount = get_account_type_based_gl_data(company,
			fiscal_year.get("year_start_date"), fiscal_year.get("year_end_date"), account_type, filters)

		if amount and account_type == "Depreciation":
			amount *= -1

		total += amount
		data.setdefault(company, amount)

	data["total"] = total
	return data

def get_columns(companies, periodicity, period_list, accumulated_in_group_company=1):
	columns = [{
		"fieldname": "account",
		"label": _("Account"),
		"fieldtype": "Link",
		"options": "Account",
		"width": 300
	}]

	columns.append({
		"fieldname": "currency",
		"label": _("Currency"),
		"fieldtype": "Link",
		"options": "Currency",
		"hidden": 1
	})

	# for company in companies:
	# 	columns.append({
	# 		"fieldname": company,
	# 		"label": company,
	# 		"fieldtype": "Currency",
	# 		"options": "currency",
	# 		"width": 150
	# 	})
	for company in companies:
		for period in period_list:
			columns.append({
				"fieldname": f'{company.lower()}_{period.key}',
				"label": f'{company} {period.label}',
				"fieldtype": "Currency",
				"options": "currency",
				"width": 150
			})
		if periodicity!="Yearly":
			if not accumulated_in_group_company:
				columns.append({
					"fieldname": "total",
					"label": f'{company} Total',
					"fieldtype": "Currency",
					"width": 150
				})

	return columns

def get_data(companies, root_type, balance_must_be, period_list, filters=None, ignore_closing_entries=False, cost_center_wise=False):
	accounts, accounts_by_name = get_account_heads(root_type,
		companies, filters)

	if not accounts: return []

	company_currency = get_company_currency(filters)

	gl_entries_by_account = {}
	for root in frappe.db.sql("""select lft, rgt from tabAccount
			where root_type=%s and ifnull(parent_account, '') = ''""", root_type, as_dict=1):

		set_gl_entries_by_account(
			period_list[0]["year_start_date"],
			period_list[-1]["to_date"], root.lft, root.rgt, filters,
			gl_entries_by_account, accounts_by_name, ignore_closing_entries=False)

	calculate_values(accounts_by_name, gl_entries_by_account, companies, period_list, filters, cost_center_wise=cost_center_wise)
	accumulate_values_into_parents(accounts, accounts_by_name, companies)
	out = prepare_data(accounts, period_list, balance_must_be, companies, company_currency)

	if out:
		add_total_row(out, root_type, balance_must_be, companies, company_currency)

	return out

def get_company_currency(filters=None):
	return (filters.get('presentation_currency')
		or frappe.get_cached_value('Company',  filters.company,  "default_currency"))

def calculate_values(accounts_by_name, gl_entries_by_account, companies, period_list, filters, cost_center_wise=False):
	for entries in gl_entries_by_account.values():
		for entry in entries:
			key = entry.account_number or entry.account_name
			d = accounts_by_name.get(key)
			if d:
				for company in companies:
					# check if posting date is within the period
					company_key = company.lower()
					#company_value = f'{company_key}_value'
					company_value = 0.0
					for period in period_list:
						if entry.posting_date <= period.to_date:
							if (cost_center_wise):
								if (entry.cost_center == company or (filters.get('accumulated_in_group_company'))
									and entry.cost_center in companies.get(company)):
									d[f'{company_key}_{period.key}'] = company_value + flt(entry.debit) - flt(entry.credit)
									company_value = d[f'{company_key}_{period.key}']
									d[company] = company_value 
							else:
								if (entry.company == company or (filters.get('accumulated_in_group_company'))
									and entry.company in companies.get(company)):
									d[f'{company_key}_{period.key}'] = company_value + flt(entry.debit) - flt(entry.credit)
									company_value = d[f'{company_key}_{period.key}']
									d[company] = company_value

					if getdate(entry.posting_date) < period_list[0].year_start_date:
						d["opening_balance"] = d.get("opening_balance", 0.0) + flt(entry.debit) - flt(entry.credit)

def accumulate_values_into_parents(accounts, accounts_by_name, companies):
	"""accumulate children's values in parent accounts"""
	for d in reversed(accounts):
		if d.parent_account:
			account = d.parent_account.split('-')[0].strip()
			if not accounts_by_name.get(account):
				continue

			for company in companies:
				accounts_by_name[account][company] = \
					accounts_by_name[account].get(company, 0.0) + d.get(company, 0.0)

			accounts_by_name[account]["opening_balance"] = \
				accounts_by_name[account].get("opening_balance", 0.0) + d.get("opening_balance", 0.0)

def get_account_heads(root_type, companies, filters):
	accounts = get_accounts(root_type, filters)

	if not accounts:
		return None, None

	accounts, accounts_by_name, parent_children_map = filter_accounts(accounts)

	return accounts, accounts_by_name

def get_companies(filters):
	companies = {}
	all_companies = get_subsidiary_companies(filters.get('company'))
	companies.setdefault(filters.get('company'), all_companies)

	for d in all_companies:
		if d not in companies:
			subsidiary_companies = get_subsidiary_companies(d)
			companies.setdefault(d, subsidiary_companies)

	return all_companies, companies

def get_subsidiary_companies(company):
	lft, rgt = frappe.get_cached_value('Company',
		company,  ["lft", "rgt"])

	return frappe.db.sql_list("""select name from `tabCompany`
		where lft >= {0} and rgt <= {1} order by lft, rgt""".format(lft, rgt))

def get_accounts(root_type, filters):
	return frappe.db.sql(""" select name, is_group, company,
			parent_account, lft, rgt, root_type, report_type, account_name, account_number
		from
			`tabAccount` where company = %s and root_type = %s
		""" , (filters.get('company'), root_type), as_dict=1)

def prepare_data(accounts, period_list, balance_must_be, companies, company_currency):
	data = []
	#year_start_date = fiscal_year.get("year_start_date")
	#year_end_date = fiscal_year.get("year_end_date")
	year_start_date = period_list[0]["year_start_date"].strftime("%Y-%m-%d")
	year_end_date = period_list[-1]["year_end_date"].strftime("%Y-%m-%d")

	for d in accounts:
		# add to output
		has_value = False
		total = 0
		row = frappe._dict({
			"account_name": _(d.account_name),
			"account": _(d.account_name),
			"parent_account": _(d.parent_account),
			"indent": flt(d.indent),
			"year_start_date": year_start_date,
			"year_end_date": year_end_date,
			"currency": company_currency,
			"opening_balance": d.get("opening_balance", 0.0) * (1 if balance_must_be == "Debit" else -1)
		})
		for company in companies:
			company_key = company.lower()
			
			for period in period_list:
				period_key = f'{company_key}_{period.key}'

				if d.get(period_key) and balance_must_be == "Credit":
					d[period_key] *= -1

				row[period_key] = flt(d.get(period_key, 0.0), 3)

				#ignore zero values
				if abs(row[period_key]) >= 0.005:
					has_value = True
					total += flt(row[period_key])

			# if d.get(company) and balance_must_be == "Credit":
			# 	# change sign based on Debit or Credit, since calculation is done using (debit - credit)
			# 	d[company] *= -1

			# row[company] = flt(d.get(company, 0.0), 3)

			# if abs(row[company]) >= 0.005:
			# 	# ignore zero values
			# 	has_value = True
			# 	total += flt(row[company])

		row["has_value"] = has_value
		row["total"] = total
		data.append(row)

	return data

def set_gl_entries_by_account(from_date, to_date, root_lft, root_rgt, filters, gl_entries_by_account,
	accounts_by_name, ignore_closing_entries=False):
	"""Returns a dict like { "account": [gl entries], ... }"""

	company_lft, company_rgt = frappe.get_cached_value('Company',
		filters.get('company'),  ["lft", "rgt"])

	additional_conditions = get_additional_conditions(from_date, ignore_closing_entries, filters)
	companies = frappe.db.sql(""" select name, default_currency from `tabCompany`
		where lft >= %(company_lft)s and rgt <= %(company_rgt)s""", {
			"company_lft": company_lft,
			"company_rgt": company_rgt,
		}, as_dict=1)

	currency_info = frappe._dict({
		'report_date': to_date,
		'presentation_currency': filters.get('presentation_currency')
	})

	for d in companies:
		gl_entries = frappe.db.sql("""select gl.posting_date, gl.account, gl.debit, gl.credit, gl.is_opening, gl.company,
			gl.fiscal_year, gl.debit_in_account_currency, gl.credit_in_account_currency, gl.account_currency, gl.cost_center,
			acc.account_name, acc.account_number
			from `tabGL Entry` gl, `tabAccount` acc where acc.name = gl.account and gl.company = %(company)s
			{additional_conditions} and gl.posting_date <= %(to_date)s and acc.lft >= %(lft)s and acc.rgt <= %(rgt)s
			order by gl.account, gl.posting_date""".format(additional_conditions=additional_conditions),
			{
				"from_date": from_date,
				"to_date": to_date,
				"lft": root_lft,
				"rgt": root_rgt,
				"company": d.name,
				"finance_book": filters.get("finance_book"),
				"company_fb": frappe.db.get_value("Company", d.name, 'default_finance_book')
			},
			as_dict=True)

		if filters and filters.get('presentation_currency') != d.default_currency:
			currency_info['company'] = d.name
			currency_info['company_currency'] = d.default_currency
			convert_to_presentation_currency(gl_entries, currency_info)

		for entry in gl_entries:
			key = entry.account_number or entry.account_name
			validate_entries(key, entry, accounts_by_name)
			gl_entries_by_account.setdefault(key, []).append(entry)

	return gl_entries_by_account

def validate_entries(key, entry, accounts_by_name):
	if key not in accounts_by_name:
		field = "Account number" if entry.account_number else "Account name"
		frappe.throw(_("{0} {1} is not present in the parent company").format(field, key))

def get_additional_conditions(from_date, ignore_closing_entries, filters):
	additional_conditions = []

	if ignore_closing_entries:
		additional_conditions.append("ifnull(gl.voucher_type, '')!='Period Closing Voucher'")

	if from_date:
		additional_conditions.append("gl.posting_date >= %(from_date)s")

	if filters.get("include_default_book_entries"):
		additional_conditions.append("(finance_book in (%(finance_book)s, %(company_fb)s, '') OR finance_book IS NULL)")
	else:
		additional_conditions.append("(finance_book in (%(finance_book)s, '') OR finance_book IS NULL)")

	return " and {}".format(" and ".join(additional_conditions)) if additional_conditions else ""

def add_total_row(out, root_type, balance_must_be, companies, company_currency):
	total_row = {
		"account_name": "'" + _("Total {0} ({1})").format(_(root_type), _(balance_must_be)) + "'",
		"account": "'" + _("Total {0} ({1})").format(_(root_type), _(balance_must_be)) + "'",
		"currency": company_currency
	}

	for row in out:
		if not row.get("parent_account"):
			for company in companies:
				total_row.setdefault(company, 0.0)
				total_row[company] += row.get(company, 0.0)
				row[company] = 0.0

			total_row.setdefault("total", 0.0)
			total_row["total"] += flt(row["total"])
			row["total"] = ""

	if "total" in total_row:
		out.append(total_row)

		# blank row after Total
		out.append({})

def filter_accounts(accounts, depth=10):
	parent_children_map = {}
	accounts_by_name = {}
	for d in accounts:
		key = d.account_number or d.account_name
		accounts_by_name[key] = d
		parent_children_map.setdefault(d.parent_account or None, []).append(d)

	filtered_accounts = []

	def add_to_list(parent, level):
		if level < depth:
			children = parent_children_map.get(parent) or []
			sort_accounts(children, is_root=True if parent==None else False)

			for child in children:
				child.indent = level
				filtered_accounts.append(child)
				add_to_list(child.name, level + 1)

	add_to_list(None, 0)

	return filtered_accounts, accounts_by_name, parent_children_map
