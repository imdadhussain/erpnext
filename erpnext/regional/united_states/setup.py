# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup(company=None, patch=True):
	make_custom_fields()
	add_print_formats()
	update_address_template()


def make_custom_fields():
	custom_fields = {
		'Supplier': [
			dict(fieldname='irs_1099', fieldtype='Check', insert_after='tax_id',
				label='Is IRS 1099 reporting required for supplier?')
		],
		'Sales Order': [
			dict(fieldname='affirm_id', fieldtype="Data", insert_after='po_date',
				label="Affirm ID", read_only=1, allow_on_submit=1),
			dict(fieldname='affirm_status', fieldtype="Data", insert_after='affirm_id',
				label="Affirm Capture Status", read_only=1, allow_on_submit=1),
			dict(fieldname='exempt_from_sales_tax', fieldtype='Check', insert_after='taxes_and_charges',
				label='Is customer exempted from sales tax?')
		],
		'Sales Invoice': [
			dict(fieldname='exempt_from_sales_tax', fieldtype='Check', insert_after='taxes_section',
				label='Is customer exempted from sales tax?')
		],
		'Customer': [
			dict(fieldname='exempt_from_sales_tax', fieldtype='Check', insert_after='represents_company',
				label='Is customer exempted from sales tax?')
		],
		'Quotation': [
			dict(fieldname='exempt_from_sales_tax', fieldtype='Check', insert_after='taxes_and_charges',
				label='Is customer exempted from sales tax?')
		],
		'Lead': [
			dict(fieldname='exempt_from_sales_tax', fieldtype='Check', insert_after='email_id',
				label='Is Lead exempted from sales tax?')
		]
	}
	create_custom_fields(custom_fields)


def add_print_formats():
	frappe.reload_doc("regional", "print_format", "irs_1099_form")
	frappe.db.sql(""" update `tabPrint Format` set disabled = 0 where
		name in('IRS 1099 Form') """)


def update_address_template():
	html = """{{ address_line1 }}<br>
		{% if address_line2 %}{{ address_line2 }}<br>{% endif -%}
		{{ city }}, {% if state %}{{ state }}{% endif -%}{% if pincode %} {{ pincode }}<br>{% endif -%}
		{% if country != "United States" %}{{ country|upper }}{% endif -%}
		"""

	address_template = frappe.db.get_value('Address Template', 'United States')
	if address_template:
		frappe.db.set_value('Address Template', 'United States', 'template', html)
	else:
		frappe.get_doc(dict(doctype='Address Template', country='United States', template=html)).insert()
