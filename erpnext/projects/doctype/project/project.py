# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from six import iteritems
import copy
from email_reply_parser import EmailReplyParser
from frappe.utils import (flt, getdate, get_url, now,
	nowtime, get_time, today, get_datetime, add_days)
from erpnext.controllers.queries import get_filters_cond
from frappe.desk.reportview import get_match_cond
from erpnext.hr.doctype.daily_work_summary.daily_work_summary import get_users_email
from erpnext.hr.doctype.holiday_list.holiday_list import is_holiday
from frappe.desk.form.assign_to import add
from frappe.model.document import Document
from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

class Project(Document):
	def onload(self):
		self.update_costing()

	def before_print(self):
		self.onload()


	def validate(self):
		if not self.is_new():
			self.copy_from_template()
		self.validate_end_date()
		self.send_welcome_email()
		self.update_costing()
		self.update_percent_complete()
		
	def copy_from_template(self):
		'''
		Copy tasks from template
		'''
		if self.project_template and not frappe.db.get_all('Task', dict(project = self.name), limit=1):

			# has a template, and no loaded tasks, so lets create
			if not self.expected_start_date:
				# project starts today
				self.expected_start_date = today()

			template = frappe.get_doc('Project Template', self.project_template)

			if not self.project_type:
				self.project_type = template.project_type

			# create tasks from template
			for task in template.tasks:
				task_doc = frappe.get_doc(dict(
					doctype = 'Task',
					subject = task.subject,
					project = self.name,
					status = 'Open',
					exp_start_date = add_days(self.expected_start_date, task.start),
					exp_end_date = add_days(self.expected_start_date, task.start + task.duration),
					description = task.description,
					task_weight = task.task_weight
				))
				task_doc.append("projects", {
					"is_default": 1,
					"project": self.name
				})
				task_doc.insert()
				if task.assigned_user:
					args = {
						'doctype': 'Task',
						'name': task_doc.name,
						'assign_to' : [task.assigned_user],
					}
					add(args)

	def validate_end_date(self):
		if self.expected_start_date and self.expected_end_date and self.expected_start_date > self.expected_end_date:
			frappe.throw(_("Expected End date cannot be greater that Expected Start Date."))

	def is_row_updated(self, row, existing_task_data, fields):
		if self.get("__islocal") or not existing_task_data: return True

		d = existing_task_data.get(row.task_id, {})

		for field in fields:
			if row.get(field) != d.get(field):
				return True

	def update_project(self):
		'''Called externally by Task'''
		self.update_percent_complete()
		self.update_costing()
		self.db_update()

	def after_insert(self):
		self.copy_from_template()
		if self.sales_order:
			frappe.db.set_value("Sales Order", self.sales_order, "project", self.name)

	def update_percent_complete(self):
		total = frappe.db.count('Task Project', {"project": self.name, "status": ['!=', 'Closed']})
		complete_statuses = ['Completed']

		#needs to be replaced with a Table Multiselect after status is changed into a linked feild.
		if self.task_completion_statuses:
			complete_statuses = list(self.task_completion_statuses.split(","))

		if not total:
			self.percent_complete = 0
		else:
			if self.use_task_weight:
				weight_sum = frappe.db.sql("""select sum(task.task_weight) from `tabTask` task, `tabTask Project` task_project 
					where task.name=task_project.parent and task_project.project=%s""", self.name)[0][0]
				weighted_progress = frappe.db.sql("""select task_project.status status, task_weight from `tabTask` task, `tabTask Project` task_project 
					where task.name=task_project.parent and task_project.project=%s""", self.name, as_dict=1)
				pct_complete = 0
				for row in weighted_progress:
					if row["status"] in complete_statuses:
						pct_complete += frappe.utils.safe_div(row["task_weight"], weight_sum) *100
				self.percent_complete = flt(flt(pct_complete), 2)
			else:
				completed = frappe.db.sql("""select count(name) from `tabTask Project` where
					project=%s and status in %s""", (self.name, complete_statuses))[0][0]
				self.percent_complete = flt(flt(completed) / total * 100, 2)

		# don't update status if it is cancelled
		if self.status == 'Cancelled':
			return

		if self.percent_complete == 100:
			self.status = "Completed"

		else:
			self.status = "Open"

	def update_costing(self):
		from_time_sheet = frappe.db.sql("""select
			sum(costing_amount) as costing_amount,
			sum(billing_amount) as billing_amount,
			min(from_time) as start_date,
			max(to_time) as end_date,
			sum(hours) as time
			from `tabTimesheet Detail` where project = %s and docstatus = 1""", self.name, as_dict=1)[0]

		from_expense_claim = frappe.db.sql("""select
			sum(total_sanctioned_amount) as total_sanctioned_amount
			from `tabExpense Claim` where project = %s
			and docstatus = 1""", self.name, as_dict=1)[0]

		self.actual_start_date = from_time_sheet.start_date
		self.actual_end_date = from_time_sheet.end_date

		self.total_costing_amount = from_time_sheet.costing_amount
		self.total_billable_amount = from_time_sheet.billing_amount
		self.actual_time = from_time_sheet.time

		self.total_expense_claim = from_expense_claim.total_sanctioned_amount
		self.update_purchase_costing()
		self.update_sales_amount()
		self.update_billed_amount()
		self.calculate_gross_margin()

	def calculate_gross_margin(self):
		expense_amount = (flt(self.total_costing_amount) + flt(self.total_expense_claim)
			+ flt(self.total_purchase_cost) + flt(self.get('total_consumed_material_cost', 0)))

		self.gross_margin = flt(self.total_billed_amount) - expense_amount
		if self.total_billed_amount:
			self.per_gross_margin = (self.gross_margin / flt(self.total_billed_amount)) * 100

	def update_purchase_costing(self):
		total_purchase_cost = frappe.db.sql("""select sum(base_net_amount)
			from `tabPurchase Invoice Item` where project = %s and docstatus=1""", self.name)

		self.total_purchase_cost = total_purchase_cost and total_purchase_cost[0][0] or 0

	def update_sales_amount(self):
		total_sales_amount = frappe.db.sql("""select sum(base_net_total)
			from `tabSales Order` where project = %s and docstatus=1""", self.name)

		self.total_sales_amount = total_sales_amount and total_sales_amount[0][0] or 0

	def update_billed_amount(self):
		total_billed_amount = frappe.db.sql("""select sum(base_net_total)
			from `tabSales Invoice` where project = %s and docstatus=1""", self.name)

		self.total_billed_amount = total_billed_amount and total_billed_amount[0][0] or 0

	def after_rename(self, old_name, new_name, merge=False):
		if old_name == self.copied_from:
			frappe.db.set_value('Project', new_name, 'copied_from', new_name)

	def send_welcome_email(self):
		url = get_url("/project/?name={0}".format(self.name))
		messages = (
			_("You have been invited to collaborate on the project: {0}".format(self.name)),
			url,
			_("Join")
		)

		content = """
		<p>{0}.</p>
		<p><a href="{1}">{2}</a></p>
		"""

		for user in self.users:
			if user.welcome_email_sent == 0:
				frappe.sendmail(user.user, subject=_("Project Collaboration Invitation"),
								content=content.format(*messages))
				user.welcome_email_sent = 1

	def on_update(self):
		self.notify()


	def notify(self):
		if not frappe.db.get_single_value("Projects Settings", "send_notifications_for_project"):
			return

		notification_doc = {
			'type': 'Notify',
			'document_type': self.doctype,
			'subject': _("Project {0} has been updated.").format("<a href='{0}'>{1}</a>".format(self.get_url(), frappe.bold(self.name))),
			'document_name': self.name,
			'from_user': frappe.session.user
		}

		enqueue_create_notification(self.get_assigned_users(), notification_doc)

		for user in self.get_assigned_users():
			if user == frappe.session.user:
				continue

			frappe.publish_realtime('show_notification_alert', message=notification_doc.get("subject"), after_commit=True, user=user)

def get_timeline_data(doctype, name):
	'''Return timeline for attendance'''
	return dict(frappe.db.sql('''select unix_timestamp(from_time), count(*)
		from `tabTimesheet Detail` where project=%s
			and from_time > date_sub(curdate(), interval 1 year)
			and docstatus < 2
			group by date(from_time)''', name))


def get_project_list(doctype, txt, filters, limit_start, limit_page_length=20, order_by="modified"):
	return frappe.db.sql('''select distinct project.*
		from tabProject project, `tabProject User` project_user
		where
			(project_user.user = %(user)s
			and project_user.parent = project.name)
			or project.owner = %(user)s
			order by project.modified desc
			limit {0}, {1}
		'''.format(limit_start, limit_page_length),
						 {'user': frappe.session.user},
						 as_dict=True,
						 update={'doctype': 'Project'})


def get_list_context(context=None):
	return {
		"show_sidebar": True,
		"show_search": True,
		'no_breadcrumbs': True,
		"title": _("Projects"),
		"get_list": get_project_list,
		"row_template": "templates/includes/projects/project_row.html"
	}

def get_users_for_project(doctype, txt, searchfield, start, page_len, filters):
	conditions = []
	return frappe.db.sql("""select name, concat_ws(' ', first_name, middle_name, last_name)
		from `tabUser`
		where enabled=1
			and name not in ("Guest", "Administrator")
			and ({key} like %(txt)s
				or full_name like %(txt)s)
			{fcond} {mcond}
		order by
			if(locate(%(_txt)s, name), locate(%(_txt)s, name), 99999),
			if(locate(%(_txt)s, full_name), locate(%(_txt)s, full_name), 99999),
			idx desc,
			name, full_name
		limit %(start)s, %(page_len)s""".format(**{
		'key': searchfield,
		'fcond': get_filters_cond(doctype, filters, conditions),
		'mcond': get_match_cond(doctype)
	}), {
							 'txt': "%%%s%%" % txt,
							 '_txt': txt.replace("%", ""),
							 'start': start,
							 'page_len': page_len
						 })


@frappe.whitelist()
def get_cost_center_name(project):
	return frappe.db.get_value("Project", project, "cost_center")

def hourly_reminder():
	fields = ["from_time", "to_time"]
	projects = get_projects_for_collect_progress("Hourly", fields)

	for project in projects:
		if (get_time(nowtime()) >= get_time(project.from_time) or
			get_time(nowtime()) <= get_time(project.to_time)):
			send_project_update_email_to_users(project.name)

def project_status_update_reminder():
	daily_reminder()
	twice_daily_reminder()
	weekly_reminder()

def daily_reminder():
	fields = ["daily_time_to_send"]
	projects =  get_projects_for_collect_progress("Daily", fields)

	for project in projects:
		if allow_to_make_project_update(project.name, project.get("daily_time_to_send"), "Daily"):
			send_project_update_email_to_users(project.name)

def twice_daily_reminder():
	fields = ["first_email", "second_email"]
	projects =  get_projects_for_collect_progress("Twice Daily", fields)
	fields.remove("name")

	for project in projects:
		for d in fields:
			if allow_to_make_project_update(project.name, project.get(d), "Twicely"):
				send_project_update_email_to_users(project.name)

def weekly_reminder():
	fields = ["day_to_send", "weekly_time_to_send"]
	projects =  get_projects_for_collect_progress("Weekly", fields)

	current_day = get_datetime().strftime("%A")
	for project in projects:
		if current_day != project.day_to_send:
			continue

		if allow_to_make_project_update(project.name, project.get("weekly_time_to_send"), "Weekly"):
			send_project_update_email_to_users(project.name)

def allow_to_make_project_update(project, time, frequency):
	data = frappe.db.sql(""" SELECT name from `tabProject Update`
		WHERE project = %s and date = %s """, (project, today()))

	# len(data) > 1 condition is checked for twicely frequency
	if data and (frequency in ['Daily', 'Weekly'] or len(data) > 1):
		return False

	if get_time(nowtime()) >= get_time(time):
		return True


@frappe.whitelist()
def create_duplicate_project(prev_doc, project_name):
	''' Create duplicate project based on the old project '''
	import json
	prev_doc = json.loads(prev_doc)

	if project_name == prev_doc.get('name'):
		frappe.throw(_("Use a name that is different from previous project name"))

	# change the copied doc name to new project name
	project = frappe.copy_doc(prev_doc)
	project.name = project_name
	project.project_template = ''
	project.project_name = project_name
	project.status = 'Open'
	project.percent_complete = 0
	project.insert()

	# fetch all the task linked with the old project
	task_list = frappe.get_all("Task", filters={
		'project': prev_doc.get('name')
	}, fields=['name'])

	# Create duplicate task for all the task
	new_task_list = []
	for task in task_list:
		task = frappe.get_doc('Task', task)
		new_task = frappe.copy_doc(task)
		new_task.project = project.name
		new_task.parent_task = None
		new_task.depends_on = None
		new_task.status = 'Open'
		new_task.completed_by = ''
		new_task.insert()
		assigned_user = frappe.db.get_value("ToDo", filters={'reference_name' : task.name}, fieldname="owner")
		if assigned_user:
			args = {
				'doctype': 'Task',
				'name': new_task.name,
				'assign_to' : assigned_user,
			}
			add(args)
		task_dict = {
			'previous_task_name':task.name,
			'new_task_name':new_task.name,
		}
		new_task_list.append(task_dict)

	handle_task_linking(new_task_list)

	project.db_set('project_template', prev_doc.get('project_template'))

def handle_task_linking(new_task_list):
	for task in new_task_list:
		old_task = frappe.get_doc('Task', task['previous_task_name'])
		new_task = frappe.get_doc('Task', task['new_task_name'])
		if old_task.parent_task:
			for item in new_task_list:
				if old_task.parent_task == item['previous_task_name']:
					new_task.parent_task = item['new_task_name']
		new_task.save()

def get_projects_for_collect_progress(frequency, fields):
	fields.extend(["name"])

	return frappe.get_all("Project", fields = fields,
		filters = {'collect_progress': 1, 'frequency': frequency, 'status': 'Open'})

def send_project_update_email_to_users(project):
	doc = frappe.get_doc('Project', project)

	if is_holiday(doc.holiday_list) or not doc.users: return

	project_update = frappe.get_doc({
		"doctype" : "Project Update",
		"project" : project,
		"sent": 0,
		"date": today(),
		"time": nowtime(),
		"naming_series": "UPDATE-.project.-.YY.MM.DD.-",
	}).insert()

	subject = "For project %s, update your status" % (project)

	incoming_email_account = frappe.db.get_value('Email Account',
		dict(enable_incoming=1, default_incoming=1), 'email_id')

	frappe.sendmail(recipients=get_users_email(doc),
		message=doc.message,
		subject=_(subject),
		reference_doctype=project_update.doctype,
		reference_name=project_update.name,
		reply_to=incoming_email_account
	)

def collect_project_status():
	for data in frappe.get_all("Project Update",
		{'date': today(), 'sent': 0}):
		replies = frappe.get_all('Communication',
			fields=['content', 'text_content', 'sender'],
			filters=dict(reference_doctype="Project Update",
				reference_name=data.name,
				communication_type='Communication',
				sent_or_received='Received'),
			order_by='creation asc')

		for d in replies:
			doc = frappe.get_doc("Project Update", data.name)
			user_data = frappe.db.get_values("User", {"email": d.sender},
				["full_name", "user_image", "name"], as_dict=True)[0]

			doc.append("users", {
				'user': user_data.name,
				'full_name': user_data.full_name,
				'image': user_data.user_image,
				'project_status': frappe.utils.md_to_html(
					EmailReplyParser.parse_reply(d.text_content) or d.content
				)
			})

			doc.save(ignore_permissions=True)

def send_project_status_email_to_users():
	yesterday = add_days(today(), -1)

	for d in frappe.get_all("Project Update",
		{'date': yesterday, 'sent': 0}):
		doc = frappe.get_doc("Project Update", d.name)

		project_doc = frappe.get_doc('Project', doc.project)

		args = {
			"users": doc.users,
			"title": _("Project Summary for {0}").format(yesterday)
		}

		frappe.sendmail(recipients=get_users_email(project_doc),
			template='daily_project_summary',
			args=args,
			subject=_("Daily Project Summary for {0}").format(d.name),
			reference_doctype="Project Update",
			reference_name=d.name)

		doc.db_set('sent', 1)

def update_project_sales_billing():
	sales_update_frequency = frappe.db.get_single_value("Selling Settings", "sales_update_frequency")
	if sales_update_frequency == "Each Transaction":
		return
	elif (sales_update_frequency == "Monthly" and frappe.utils.now_datetime().day != 1):
		return

	#Else simply fallback to Daily
	exists_query = '(SELECT 1 from `tab{doctype}` where docstatus = 1 and project = `tabProject`.name)'
	project_map = {}
	for project_details in frappe.db.sql('''
			SELECT name, 1 as order_exists, null as invoice_exists from `tabProject` where
			exists {order_exists}
			union
			SELECT name, null as order_exists, 1 as invoice_exists from `tabProject` where
			exists {invoice_exists}
		'''.format(
			order_exists=exists_query.format(doctype="Sales Order"),
			invoice_exists=exists_query.format(doctype="Sales Invoice"),
		), as_dict=True):
		project = project_map.setdefault(project_details.name, frappe.get_doc('Project', project_details.name))
		if project_details.order_exists:
			project.update_sales_amount()
		if project_details.invoice_exists:
			project.update_billed_amount()

	for project in project_map.values():
		project.save()

@frappe.whitelist()
def create_kanban_board_if_not_exists(project):
	from frappe.desk.doctype.kanban_board.kanban_board import quick_kanban_board

	if not frappe.db.exists('Kanban Board', project):
		quick_kanban_board('Task', project, 'status')

	return True

@frappe.whitelist()
def set_project_status(project, status):
	'''
	set status for project and all related tasks
	'''
	if not status in ('Completed', 'Cancelled'):
		frappe.throw(_('Status must be Cancelled or Completed'))

	project = frappe.get_doc('Project', project)
	frappe.has_permission(doc = project, throw = True)

	for task in frappe.get_all('Task', dict(project = project.name)):
		frappe.db.set_value('Task', task.name, 'status', status)

	project.status = status
	project.save()

@frappe.whitelist()
def update_task_projects(ref_dt, ref_dn, freeze):
	task_projects = frappe.get_all("Task Project", filters={frappe.scrub(ref_dt): ref_dn})
	for project in task_projects:
		frappe.db.set_value("Task Project", project.name, "freeze", freeze)