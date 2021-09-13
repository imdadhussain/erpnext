import json
import frappe
from frappe.utils import get_url
from erpnext.stock.doctype.batch.batch import get_batch_qty

@frappe.whitelist()
def get_contact(doctype, name, contact_field):

	contact = frappe.db.get_value(doctype, name, contact_field)

	contact_persons = frappe.db.sql(
		"""
			SELECT parent,
				(SELECT is_primary_contact FROM tabContact c WHERE c.name = dl.parent) AS is_primary_contact
			FROM
				`tabDynamic Link` dl
			WHERE
				dl.link_doctype=%s
				AND dl.link_name=%s
				AND dl.parenttype = "Contact"
		""", (frappe.unscrub(contact_field), contact), as_dict=1)

	if contact_persons:
		for contact_person in contact_persons:
			contact_person.email_id = frappe.db.get_value("Contact", contact_person.parent, ["email_id"])
			if contact_person.is_primary_contact:
				return contact_person

		contact_person = contact_persons[0]

		return contact_person

@frappe.whitelist()
def get_document_links(doctype, docs):
	docs = json.loads(docs)
	print_format = "print_format"
	links = []
	for doc in docs:
		link = frappe.get_template("templates/emails/print_link.html").render({
			"url": get_url(),
			"doctype": doctype,
			"name": doc.get("name"),
			"print_format": print_format,
			"key": frappe.get_doc(doctype, doc.get("name")).get_signature()
		})
		links.append(link)
	return links

@frappe.whitelist()
def create_authorization_request(dt, dn, contact_email, contact_name):
	new_authorization_request = frappe.new_doc("Authorization Request")
	new_authorization_request.linked_doctype = dt
	new_authorization_request.linked_docname = dn
	new_authorization_request.authorizer_email = contact_email
	new_authorization_request.authorizer_name = contact_name
	new_authorization_request.save()


@frappe.whitelist()
def move_expired_batches(source_name, target_doc=None):
	batch_details = get_batch_qty(source_name)
	target_warehouse = frappe.flags.args.get("warehouse")

	item = frappe.db.get_value("Batch", source_name, "item")
	uom = frappe.db.get_value("Item", item, "stock_uom")

	stock_entry = frappe.new_doc("Stock Entry")
	stock_entry.stock_entry_type = "Material Transfer"

	for batch in batch_details:
		if batch.get("qty") > 0:
			stock_entry.append("items", {
				"item_code": item,
				"qty": batch.get("qty"),
				"uom": uom,
				"stock_uom": uom,
				"batch_no": source_name,
				"s_warehouse": batch.get("warehouse"),
				"t_warehouse": target_warehouse
			})

	return stock_entry