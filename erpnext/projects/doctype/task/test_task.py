# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
from __future__ import unicode_literals
import frappe
import unittest
from frappe.utils import getdate, nowdate, add_days

from erpnext.projects.doctype.task.task import CircularReferenceError

class TestTask(unittest.TestCase):
	def test_circular_reference(self):
		task1 = create_task("_Test Task 1", add_days(nowdate(), -15), add_days(nowdate(), -10))
		task2 = create_task("_Test Task 2", add_days(nowdate(), 11), add_days(nowdate(), 15), task1.name)
		task3 = create_task("_Test Task 3", add_days(nowdate(), 11), add_days(nowdate(), 15), task2.name)

		task1.reload()
		task1.append("depends_on", {
			"task": task3.name
		})

		self.assertRaises(CircularReferenceError, task1.save)

		task1.set("depends_on", [])
		task1.save()

		task4 = create_task("_Test Task 4", nowdate(), add_days(nowdate(), 15), task1.name)

		task3.append("depends_on", {
			"task": task4.name
		})

	def test_reschedule_dependent_task(self):
		task1 = create_task("_Test Task 1", nowdate(), add_days(nowdate(), 10))

		task2 = create_task("_Test Task 2", add_days(nowdate(), 11), add_days(nowdate(), 15), task1.name)
		task2.get("depends_on")[0].project = "_Test Project"
		task2.save()

		task3 = create_task("_Test Task 3", add_days(nowdate(), 11), add_days(nowdate(), 15), task2.name)
		task3.get("depends_on")[0].project = "_Test Project"
		task3.save()

		task1.reload()
		task1.update({
			"exp_end_date": add_days(nowdate(), 20)
		})
		task1.save()

		self.assertEqual(frappe.db.get_value("Task", task2.name, "exp_start_date"),
			getdate(add_days(nowdate(), 21)))
		self.assertEqual(frappe.db.get_value("Task", task2.name, "exp_end_date"),
			getdate(add_days(nowdate(), 25)))

		self.assertEqual(frappe.db.get_value("Task", task3.name, "exp_start_date"),
			getdate(add_days(nowdate(), 26)))
		self.assertEqual(frappe.db.get_value("Task", task3.name, "exp_end_date"),
			getdate(add_days(nowdate(), 30)))

	def test_complete_task_without_assignment_closing(self):
		if not frappe.db.exists("Task", "Test Close Assignment 1"):
			task = frappe.new_doc("Task")
			task.subject = "Test Close Assignment 1"
			task.insert()

		frappe.db.set_value("Projects Settings", None,
			"remove_assignment_on_task_completion", 0)

		def assign():
			from frappe.desk.form import assign_to
			assign_to.add({
				"assign_to": ["test@example.com"],
				"doctype": task.doctype,
				"name": task.name,
				"description": "Close this task"
			})

		def get_owner_and_status():
			return frappe.db.get_value("ToDo",
				filters={"reference_type": task.doctype, "reference_name": task.name,
					"description": "Close this task"},
				fieldname=("owner", "status"), as_dict=True)

		assign()
		todo = get_owner_and_status()
		self.assertEqual(todo.owner, "test@example.com")
		self.assertEqual(todo.status, "Open")

		# assignment should be
		task.load_from_db()
		task.status = "Completed"
		task.save()
		todo = get_owner_and_status()
		self.assertEqual(todo.owner, "test@example.com")
		self.assertEqual(todo.status, "Open")

	def test_complete_task_with_assignment_closing(self):
		if not frappe.db.exists("Task", "Test Close Assignment 2"):
			task = frappe.new_doc("Task")
			task.subject = "Test Close Assignment 2"
			task.insert()

		frappe.db.set_value("Projects Settings", None,
			"remove_assignment_on_task_completion", 1)

		def assign():
			from frappe.desk.form import assign_to
			assign_to.add({
				"assign_to": ["test@example.com"],
				"doctype": task.doctype,
				"name": task.name,
				"description": "Close this task"
			})

		def get_owner_and_status():
			return frappe.db.get_value("ToDo",
				filters={"reference_type": task.doctype, "reference_name": task.name,
					"description": "Close this task"},
				fieldname=("owner", "status"), as_dict=True)

		assign()
		todo = get_owner_and_status()
		self.assertEqual(todo.owner, "test@example.com")
		self.assertEqual(todo.status, "Open")

		# assignment should be
		task.load_from_db()
		task.status = "Completed"
		task.save()
		todo = get_owner_and_status()
		self.assertEqual(todo.owner, "test@example.com")
		self.assertEqual(todo.status, "Closed")

	def test_overdue(self):
		task = create_task("Testing Overdue", add_days(nowdate(), -10), add_days(nowdate(), -5))

		from erpnext.projects.doctype.task.task import set_tasks_as_overdue
		set_tasks_as_overdue()

		self.assertEqual(frappe.db.get_value("Task", task.name, "status"), "Overdue")

def create_task(subject, start=None, end=None, depends_on=None, project=None, save=True):
	if not frappe.db.exists("Task", subject):
		task = frappe.new_doc('Task')
		task.status = "Open"
		task.subject = subject
		task.exp_start_date = start or nowdate()
		task.exp_end_date = end or nowdate()
		task.project = project or "_Test Project"
		if save:
			task.save()
	else:
		task = frappe.get_doc("Task", subject)

	if depends_on:
		task.append("depends_on", {
			"task": depends_on
		})
		if save:
			task.save()

	return task
