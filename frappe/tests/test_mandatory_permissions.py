"""Opt-in authorization boundaries remain AND conditions around framework grants."""

from contextlib import contextmanager
from unittest.mock import patch

import frappe
import frappe.share
from frappe.core.doctype.doctype.test_doctype import new_doctype
from frappe.model.db_query import DatabaseQuery as LegacyDatabaseQuery
from frappe.tests import IntegrationTestCase


def boundary_permission(doc, ptype, user=None, **kwargs):
	if doc.some_fieldname == "abstain_true":
		return True
	return False if doc.some_fieldname == "denied" else None


def boundary_query(user=None, doctype=None):
	return f"`tab{doctype}`.`some_fieldname` != 'denied'"


class TestMandatoryPermissions(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.suffix = frappe.generate_hash(length=8)
		cls.role = "Mandatory Boundary " + cls.suffix
		frappe.get_doc(doctype="Role", role_name=cls.role, desk_access=1).insert()
		cls.reader = cls.make_user("reader", [cls.role])
		cls.share_only = cls.make_user("shared", [])
		cls.open_type = "Test Mandatory Open " + cls.suffix
		cls.owner_type = "Test Mandatory Owner " + cls.suffix
		for name, if_owner in ((cls.open_type, 0), (cls.owner_type, 1)):
			new_doctype(
				name,
				permissions=[{"role": cls.role, "read": 1, "write": 1, "if_owner": if_owner}],
			).insert()
		cls.link_type = "Test Mandatory Link " + cls.suffix
		new_doctype(
			cls.link_type,
			fields=[
				{"fieldname": field, "fieldtype": "Link", "label": field, "options": cls.open_type}
				for field in ("first_link", "second_link")
			],
			permissions=[{"role": cls.role, "read": 1}],
		).insert()

	@classmethod
	def make_user(cls, label, roles):
		return (
			frappe.get_doc(
				doctype="User",
				email=f"mandatory-{label}-{cls.suffix}@example.test",
				first_name="Mandatory boundary",
				send_welcome_email=0,
				roles=[{"role": role} for role in roles],
			)
			.insert()
			.name
		)

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for doctype in (cls.link_type, cls.owner_type, cls.open_type):
			frappe.delete_doc("DocType", doctype, force=True)
		for user in (cls.reader, cls.share_only):
			frappe.delete_doc("User", user, force=True)
		frappe.delete_doc("Role", cls.role, force=True)
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		frappe.db.savepoint("mandatory_permissions_case")
		self.addCleanup(frappe.db.rollback, save_point="mandatory_permissions_case")
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")

	def make_record(self, doctype, value="denied", owner="Administrator"):
		doc = frappe.get_doc(doctype=doctype, some_fieldname=value).insert(ignore_permissions=True)
		frappe.db.set_value(doctype, doc.name, "owner", owner, update_modified=False)
		doc.owner = owner
		return doc

	@contextmanager
	def hooks(self, enabled=True, wildcard=False):
		# Replace only hook configuration: all role, owner, share and query checks are real.
		original = frappe.get_hooks
		targets = ["*"] if wildcard else [self.open_type, self.owner_type]

		def get_hooks(hook=None, *args, **kwargs):
			if hook in ("mandatory_has_permission", "mandatory_permission_query_conditions"):
				method = "boundary_permission" if hook == "mandatory_has_permission" else "boundary_query"
				return {name: [f"{__name__}.{method}"] for name in targets} if enabled else {}
			return original(hook, *args, **kwargs)

		with patch.object(frappe, "get_hooks", side_effect=get_hooks):
			yield

	def names(self, doctype, engine, ignore_permissions=False):
		if engine == "legacy":
			rows = LegacyDatabaseQuery(doctype).execute(
				fields=["name"], limit_page_length=0, ignore_permissions=ignore_permissions
			)
		else:
			rows = frappe.get_list(
				doctype, fields=["name"], limit_page_length=0, ignore_permissions=ignore_permissions
			)
		return {row.name for row in rows}

	def count(self, doctype, engine):
		if engine == "legacy":
			rows = LegacyDatabaseQuery(doctype).execute(fields=["count(name) as total"])
		else:
			rows = frappe.get_list(doctype, fields=[{"COUNT": "name", "as": "total"}], order_by=None)
		return rows[0].total

	def test_unregistered_hooks_preserve_role_owner_and_share_grants(self):
		role_doc = self.make_record(self.open_type)
		owned_doc = self.make_record(self.owner_type, owner=self.reader)
		shared_doc = self.make_record(self.owner_type)
		frappe.share.add(self.owner_type, shared_doc.name, self.reader, read=1, write=1)
		frappe.set_user(self.reader)
		with self.hooks(enabled=False):
			for doc in (role_doc, owned_doc, shared_doc):
				self.assertTrue(frappe.has_permission(doc.doctype, "read", doc=doc))
				self.assertTrue(frappe.has_permission(doc.doctype, "write", doc=doc))
			for engine in ("legacy", "query_builder"):
				with self.subTest(engine=engine):
					self.assertIn(role_doc.name, self.names(self.open_type, engine))
					self.assertEqual(self.names(self.owner_type, engine), {owned_doc.name, shared_doc.name})

	def test_mandatory_document_hook_denies_role_owner_and_shared_documents(self):
		role_doc = self.make_record(self.open_type)
		owned_doc = self.make_record(self.owner_type, owner=self.reader)
		shared_doc = self.make_record(self.owner_type)
		frappe.share.add(self.owner_type, shared_doc.name, self.reader, read=1, write=1)
		allowed = self.make_record(self.open_type, value="allowed")
		frappe.set_user(self.reader)
		with self.hooks():
			for doc in (role_doc, owned_doc, shared_doc):
				for ptype in ("read", "write"):
					with self.subTest(doctype=doc.doctype, name=doc.name, ptype=ptype):
						self.assertFalse(frappe.has_permission(doc.doctype, ptype, doc=doc))
						self.assertFalse(frappe.has_permission(doc.doctype, ptype, doc=doc.name))
			self.assertTrue(frappe.has_permission(allowed.doctype, "read", doc=allowed))

	def test_mandatory_queries_intersect_owner_and_share_and_filter_counts(self):
		for owner in (self.reader, "Administrator"):
			denied = self.make_record(self.owner_type, owner=owner)
			allowed = self.make_record(self.owner_type, value="allowed", owner=owner)
			frappe.share.add(self.owner_type, denied.name, self.reader)
			frappe.share.add(self.owner_type, allowed.name, self.reader)
		frappe.set_user(self.reader)
		with self.hooks():
			for engine in ("legacy", "query_builder"):
				with self.subTest(engine=engine):
					self.assertEqual(len(self.names(self.owner_type, engine)), 2)
					self.assertEqual(self.count(self.owner_type, engine), 2)

	def test_share_without_any_role_permission_cannot_bypass_mandatory_hooks(self):
		denied = self.make_record(self.open_type)
		allowed = self.make_record(self.open_type, value="allowed")
		for doc in (denied, allowed):
			frappe.share.add(self.open_type, doc.name, self.share_only)
		frappe.set_user(self.share_only)
		with self.hooks(enabled=False):
			self.assertTrue(frappe.has_permission(self.open_type, "read", doc=denied))
			for engine in ("legacy", "query_builder"):
				self.assertEqual(self.names(self.open_type, engine), {denied.name, allowed.name})
		with self.hooks():
			self.assertFalse(frappe.has_permission(self.open_type, "read", doc=denied))
			self.assertTrue(frappe.has_permission(self.open_type, "read", doc=allowed))
			for engine in ("legacy", "query_builder"):
				with self.subTest(engine=engine):
					self.assertEqual(self.names(self.open_type, engine), {allowed.name})
					self.assertEqual(self.count(self.open_type, engine), 1)

	def test_ignore_permissions_retains_internal_query_behavior(self):
		doc = self.make_record(self.open_type)
		frappe.set_user(self.reader)
		with self.hooks():
			for engine in ("legacy", "query_builder"):
				with self.subTest(engine=engine):
					self.assertNotIn(doc.name, self.names(self.open_type, engine))
					self.assertIn(doc.name, self.names(self.open_type, engine, ignore_permissions=True))

	def test_wildcard_mandatory_document_hook_and_administrator_behavior(self):
		doc = self.make_record(self.open_type)
		frappe.set_user(self.reader)
		with self.hooks(wildcard=True):
			self.assertFalse(frappe.has_permission(self.open_type, "read", doc=doc))
			frappe.set_user("Administrator")
			self.assertTrue(frappe.has_permission(self.open_type, "read", doc=doc))

	def test_true_and_none_mandatory_results_do_not_grant_missing_permissions(self):
		docs = [self.make_record(self.open_type, value=value) for value in ("allowed", "abstain_true")]
		frappe.set_user(self.share_only)
		with self.hooks():
			for doc in docs:
				self.assertFalse(frappe.has_permission(self.open_type, "read", doc=doc))

	def test_linked_fields_apply_mandatory_conditions_to_each_table_alias(self):
		denied = self.make_record(self.open_type)
		allowed = self.make_record(self.open_type, value="allowed")
		link = frappe.get_doc(
			doctype=self.link_type, first_link=allowed.name, second_link=denied.name
		).insert(ignore_permissions=True)
		frappe.set_user(self.reader)
		query_args = dict(
			fields=[
				"name",
				"first_link.some_fieldname as first_value",
				"second_link.some_fieldname as second_value",
			],
			filters={"name": link.name},
			ignore_permissions=False,
		)
		with self.hooks(enabled=False):
			row = frappe.qb.get_query(self.link_type, **query_args).run(as_dict=True)[0]
			self.assertEqual((row.first_value, row.second_value), ("allowed", "denied"))
		with self.hooks():
			row = frappe.qb.get_query(self.link_type, **query_args).run(as_dict=True)[0]
			self.assertEqual(row.first_value, "allowed")
			self.assertIsNone(row.second_value)
