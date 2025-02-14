from __future__ import unicode_literals
from frappe import _

def get_data():
	return {
		'fieldname': 'project',
		'transactions': [
			{
				'label': _('Project'),
				'items': ['Task', 'Timesheet', 'Expense Claim', 'Issue' , 'Project Update']
			},
			{
				'label': _('Material'),
				'items': ['Material Request', 'BOM', 'Stock Entry']
			},
			{
				'label': _('Sales'),
				'items': ['Sales Order', 'Delivery Note', 'Sales Invoice']
			},
			{
				'label': _('Purchase'),
				'items': ['Purchase Order', 'Purchase Receipt', 'Purchase Invoice']
			},
		]
	}
