# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

from unittest.mock import Mock, patch

import frappe
import frappe.permissions
from frappe.desk import link_title
from frappe.tests import IntegrationTestCase, UnitTestCase

EXTRA_TEST_RECORD_DEPENDENCIES = ["User"]


class TestReportLinkTitles(UnitTestCase):
	def test_empty_link_values_are_not_queried(self):
		columns = [{"fieldtype": "Link", "fieldname": "item", "options": "Target"}]
		values = [None, "", "null", "undefined", "NULL", "Undefined", " null ", "123", 124, 0]
		valid_names = {"NULL", "Undefined", " null ", "123", 124, 0}
		for rows in ([{"item": value} for value in values], [[value] for value in values]):
			with self.subTest(rows=rows):
				self.assertEqual(link_title.get_link_names_by_doctype(columns, rows), {"Target": valid_names})

		with (
			patch.object(frappe, "get_meta", return_value=frappe._dict(istable=0)),
			patch.object(frappe, "get_list", return_value=[]) as get_list,
		):
			link_title.get_link_titles("Target", "title", set(values))
			self.assertEqual(set(get_list.call_args.kwargs["filters"]["name"][1]), valid_names)
			get_list.reset_mock()
			self.assertEqual(link_title.get_link_titles("Target", "title", {"null", "undefined"}), {})
			get_list.assert_not_called()

	def test_child_titles_require_readable_parent_and_title_field(self):
		child_meta = frappe._dict(istable=1, show_title_field_in_link=1, title_field="title")
		parent_meta = Mock(istable=0)
		parent_meta.get_table_fields.return_value = [frappe._dict(fieldname="items", options="Child Target")]
		parent_meta.get_field.return_value = frappe._dict(permlevel=0)
		parent_meta.get_permlevel_access.return_value = [0]
		child = frappe._dict(
			doctype="Child Target",
			name="123",
			title="Readable child title",
			parenttype="Parent Target",
			parent="PARENT-1",
			parentfield="items",
		)
		columns = [{"fieldtype": "Link", "fieldname": "item", "options": "Child Target"}]
		real_has_permission = frappe.permissions.has_permission

		for parent_allowed, title_allowed in ((True, True), (False, True), (True, False)):
			parent_checks = []

			def check_permission(doctype, *args, **kwargs):
				if doctype == "Parent Target":
					parent_checks.append(kwargs.get("doc"))
					return parent_allowed
				return real_has_permission(doctype, *args, **kwargs)

			with (
				self.subTest(parent_allowed=parent_allowed, title_allowed=title_allowed),
				patch.object(frappe, "session", frappe._dict(user="reader@example.com")),
				patch.object(frappe, "flags", frappe._dict()),
				patch.object(
					frappe,
					"get_meta",
					side_effect=lambda dt: child_meta if dt == "Child Target" else parent_meta,
				),
				patch.object(frappe, "is_table", side_effect=lambda dt: dt == "Child Target"),
				patch.object(frappe, "get_lazy_doc", return_value=child),
				patch.object(frappe.permissions, "has_permission", side_effect=check_permission),
				patch.object(
					link_title, "get_permitted_fields", return_value=["title"] if title_allowed else []
				) as permitted_fields,
				patch.object(frappe, "get_list") as get_list,
			):
				titles = link_title.get_report_link_titles(columns, [{"item": "123"}])
				self.assertEqual(
					titles,
					{"Child Target::123": "Readable child title"} if parent_allowed and title_allowed else {},
				)
				self.assertEqual(parent_checks, ["PARENT-1"])
				get_list.assert_not_called()
				if parent_allowed:
					permitted_fields.assert_called_once_with(
						"Child Target", parenttype="Parent Target", ignore_virtual=True
					)
				else:
					permitted_fields.assert_not_called()

	def test_missing_child_does_not_break_report(self):
		with (
			patch.object(frappe, "get_meta", return_value=frappe._dict(istable=1)),
			patch.object(frappe, "get_lazy_doc", side_effect=frappe.DoesNotExistError),
			patch.object(frappe, "clear_last_message") as clear_last_message,
		):
			self.assertEqual(link_title.get_link_titles("Child Target", "title", {"missing"}), {})
			clear_last_message.assert_called_once_with()


class TestChildReportLinkTitles(IntegrationTestCase):
	def test_child_titles_use_parent_document_and_field_permissions(self):
		from frappe.core.doctype.doctype.test_doctype import new_doctype

		frappe.set_user("Administrator")
		role = frappe.get_doc(
			{"doctype": "Role", "role_name": "Test Link Titles " + frappe.generate_hash(length=6)}
		).insert()
		self.addCleanup(role.delete)
		user = frappe.get_doc("User", "test2@example.com")
		user.add_roles(role.name)
		self.addCleanup(user.remove_roles, role.name)

		child_type = new_doctype(
			istable=1,
			autoname="autoincrement",
			title_field="label_text",
			show_title_field_in_link=1,
			fields=[
				{"fieldname": "label_text", "fieldtype": "Data", "label": "Label"},
				{"fieldname": "private_title", "fieldtype": "Data", "label": "Private Title", "permlevel": 1},
			],
		).insert()
		self.addCleanup(child_type.delete, force=True)
		parent_type = new_doctype(
			fields=[
				{"fieldname": "items", "fieldtype": "Table", "options": child_type.name, "label": "Items"}
			],
			permissions=[{"role": role.name, "read": 1, "if_owner": 1}],
		).insert()
		self.addCleanup(parent_type.delete, force=True)
		parents = []
		for owner in (user.name, "Administrator"):
			parent = frappe.get_doc(
				{
					"doctype": parent_type.name,
					"items": [{"label_text": "Child of " + owner, "private_title": "Private"}],
				}
			).insert()
			parent.db_set("owner", owner)
			parents.append(parent)
			self.addCleanup(parent.delete, ignore_permissions=True)

		columns = [{"fieldtype": "Link", "fieldname": "item", "options": child_type.name}]
		rows = [{"item": str(parent.items[0].name)} for parent in parents]
		rows.extend([{"item": "null"}, {"item": "undefined"}])
		try:
			frappe.set_user(user.name)
			self.assertEqual(
				link_title.get_report_link_titles(columns, rows),
				{f"{child_type.name}::{parents[0].items[0].name}": "Child of " + user.name},
			)
			with patch.object(frappe.get_meta(child_type.name), "title_field", "private_title"):
				self.assertEqual(link_title.get_report_link_titles(columns, rows), {})
		finally:
			frappe.set_user("Administrator")
