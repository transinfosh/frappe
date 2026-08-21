# Copyright (c) 2025, Frappe Technologies and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import random_string

from frappe.desk.doctype.workspace_sidebar.workspace_sidebar import (
	get_app_sidebar_for_workspace,
	get_module_info,
)

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class IntegrationTestWorkspaceSidebar(IntegrationTestCase):
	"""
	Integration tests for WorkspaceSidebar.
	Use this class for testing interactions between multiple components.
	"""

	def test_get_app_sidebar_for_workspace(self):
		workspace_name = f"Test Workspace {random_string(8)}"
		fallback_workspace_name = f"Test Fallback Workspace {random_string(8)}"
		sidebar_title = f"Test Sidebar {random_string(8)}"
		workspace = frappe.get_doc(
			{
				"doctype": "Workspace",
				"title": workspace_name,
				"label": workspace_name,
				"module": "Desk",
				"app": "frappe",
				"public": 1,
				"content": "[]",
			}
		).insert()
		sidebar = frappe.get_doc(
			{
				"doctype": "Workspace Sidebar",
				"title": sidebar_title,
				"app": "frappe",
				"items": [
					{
						"label": "Workspace",
						"link_to": workspace_name,
						"link_type": "Workspace",
						"type": "Link",
					}
				],
			}
		).insert()
		fallback_sidebar = frappe.get_doc(
			{
				"doctype": "Workspace Sidebar",
				"title": f"Test Fallback Sidebar {random_string(8)}",
				"app": "frappe",
				"module": "Test Fallback Module",
			}
		).insert()

		try:
			self.assertEqual(
				get_app_sidebar_for_workspace(workspace_name, "frappe", "Desk"), sidebar.name
			)
			self.assertEqual(
				get_app_sidebar_for_workspace(fallback_workspace_name, "frappe", "Test Fallback Module"),
				fallback_sidebar.name,
			)
			self.assertIsNone(get_app_sidebar_for_workspace(workspace_name, "nonexistent_app", "Desk"))
		finally:
			frappe.delete_doc("Workspace Sidebar", sidebar.name, force=True)
			frappe.delete_doc("Workspace Sidebar", fallback_sidebar.name, force=True)
			frappe.delete_doc("Workspace", workspace.name, force=True)

	def test_get_module_info_includes_all_doctypes_sorted_by_name(self):
		def get_all(doctype, **kwargs):
			if doctype == "DocType":
				return ["Alpha", "Beta", "Gamma", "Omega"]
			return []

		with patch(
			"frappe.desk.doctype.workspace_sidebar.workspace_sidebar.frappe.get_all",
			side_effect=get_all,
		) as mocked_get_all:
			module_info = get_module_info("Test Module")

		self.assertEqual(module_info["DocType"], ["Alpha", "Beta", "Gamma", "Omega"])
		doctype_call = next(call for call in mocked_get_all.call_args_list if call.args[0] == "DocType")
		self.assertEqual(doctype_call.kwargs["order_by"], "name asc")
