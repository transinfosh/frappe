# Copyright (c) 2025, Frappe Technologies and Contributors
# See license.txt

import frappe
from frappe.desk.doctype.sidebar.sidebar import ShellIndex, resolve_sidebar
from frappe.desk.doctype.sidebar.test_sidebar import make_sidebar, sidebarless_module
from frappe.tests import IntegrationTestCase
from frappe.utils import random_string


class IntegrationTestWorkspaceSidebar(IntegrationTestCase):
	def test_module_workspaces_reuse_the_same_sidebar(self):
		"""The old app-sidebar fallback is now the module's workspace ownership map.

		A workspace without an explicit sidebar link still belongs to the same shell as
		the linked workspace; opening it must not create a second workspace sidebar.
		"""
		with self.set_user("Administrator"):
			module = self.enterContext(sidebarless_module(f"Test Workspace Reuse {random_string(8)}"))
			workspaces = []
			for prefix in ("Linked", "Unlisted"):
				title = f"Test {prefix} Workspace {random_string(8)}"
				workspace = frappe.get_doc(
					{
						"doctype": "Workspace",
						"title": title,
						"label": title,
						"module": module,
						"public": 1,
						"content": "[]",
					}
				).insert()
				workspaces.append(workspace.name)
				self.addCleanup(
					frappe.delete_doc, "Workspace", workspace.name, force=True, ignore_missing=True
				)

			sidebar = make_sidebar(
				module,
				title=f"Test App Sidebar {random_string(8)}",
				items=[
					{
						"label": "Workspace",
						"link_to": workspaces[0],
						"link_type": "Workspace",
						"type": "Link",
					}
				],
			)
			self.addCleanup(frappe.delete_doc, "Sidebar", sidebar.name, force=True, ignore_missing=True)
			if getattr(frappe.local, "request_cache", None):
				frappe.local.request_cache.clear()

			resolved = resolve_sidebar(sidebar.name, frappe.session.user)
			self.assertIsNotNone(resolved)
			self.assertCountEqual(resolved.workspaces, workspaces)
			owners = dict(ShellIndex({sidebar.name: resolved.as_boot_entry()}).workspace_owners())
			for workspace in workspaces:
				self.assertEqual(owners[workspace], sidebar.name)
				self.assertFalse(frappe.db.exists("Workspace Sidebar", workspace))
