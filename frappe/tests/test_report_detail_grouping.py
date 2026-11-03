# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import frappe
from frappe.desk.reportview import _validate_group_by_args, get
from frappe.tests import IntegrationTestCase


class TestReportDetailGrouping(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		previous_form_dict = frappe.local.form_dict
		self.addCleanup(setattr, frappe.local, "form_dict", previous_form_dict)
		self.addCleanup(frappe.set_user, frappe.session.user)
		frappe.set_user("Administrator")
		self.names = ["DocField", "Report", "User"]
		for name, amount in zip(self.names, [10, 20, 30], strict=True):
			frappe.db.set_value("DocType", name, "max_attachments", amount, update_modified=False)
		frappe.local.form_dict = frappe._dict(
			doctype="DocType",
			fields=["name", "module", "max_attachments"],
			filters=[["name", "in", self.names]],
			detail_group_by="`tabDocType`.`module`",
			start=0,
			page_length=1,
			order_by="name asc",
		)

	def test_totals_include_records_outside_the_loaded_page(self):
		result = get()
		self.assertEqual(len(result["values"]), 1)
		summary = result["detail_groups"]
		self.assertEqual(summary["sum_fields"], ["max_attachments"])
		self.assertEqual(summary["groups"], [{"module": "Core", "_count": 3, "max_attachments": 60}])

	def test_filters_apply_to_details_and_totals(self):
		frappe.local.form_dict.filters.append(["max_attachments", ">", 10])
		group = get()["detail_groups"]["groups"][0]
		self.assertEqual(group["_count"], 2)
		self.assertEqual(group["max_attachments"], 50)

	def test_child_filter_joins_do_not_multiply_parent_totals(self):
		frappe.local.form_dict.filters.append(["DocField", "fieldtype", "=", "Data"])
		group = get()["detail_groups"]["groups"][0]
		self.assertEqual(group["_count"], 3)
		self.assertEqual(group["max_attachments"], 60)

	def test_forbidden_group_field_is_rejected(self):
		frappe.local.form_dict.detail_group_by = "`tabUser`.`email`"
		with self.assertRaises(frappe.DataError):
			get()

	def test_child_columns_are_rejected(self):
		frappe.local.form_dict.fields.append("`tabDocField`.`fieldname`")
		with self.assertRaises(frappe.ValidationError):
			get()

	def test_group_query_respects_read_permissions(self):
		form_dict = frappe.local.form_dict
		frappe.set_user("Guest")
		frappe.local.form_dict = form_dict
		with self.assertRaises(frappe.PermissionError):
			get()

	def test_summary_mode_and_legacy_settings_remain_valid(self):
		for mode in [None, "summary", "detail"]:
			settings = {"group_by": "module", "aggregate_function": "count"}
			if mode:
				settings["mode"] = mode
			_validate_group_by_args(settings, "DocType")
		with self.assertRaises(frappe.DataError):
			_validate_group_by_args({"group_by": "module", "mode": "invalid"}, "DocType")

	def test_normal_report_response_is_unchanged(self):
		frappe.local.form_dict.pop("detail_group_by")
		self.assertNotIn("detail_groups", get())

	def test_existing_aggregate_query_still_works(self):
		frappe.local.form_dict.pop("detail_group_by")
		frappe.local.form_dict.update(
			fields=["module"],
			group_by="module",
			aggregate_on_field="name",
			aggregate_on_doctype="DocType",
			aggregate_function="count",
			order_by="_aggregate_column desc",
		)
		result = get()
		self.assertEqual(result["values"], [["Core", 3]])

	def test_detail_pagination_preserves_order_by_an_unselected_field(self):
		frappe.local.form_dict.order_by = "`tabDocType`.`creation` desc, `tabDocType`.`name` asc"
		result = get()
		self.assertIn("creation", result["keys"])
		expected = frappe.get_all(
			"DocType", filters={"name": ["in", self.names]}, order_by="creation desc, name asc", pluck="name"
		)
		self.assertEqual(result["values"][0][0], expected[0])

	def test_masked_fields_cannot_be_grouped_or_summed(self):
		from unittest.mock import patch

		from frappe.model.meta import Meta

		with patch.object(Meta, "get_masked_fields", return_value=[frappe._dict(fieldname="module")]):
			with self.assertRaises(frappe.DataError):
				get()
		with patch.object(
			Meta, "get_masked_fields", return_value=[frappe._dict(fieldname="max_attachments")]
		):
			result = get()
			self.assertEqual(result["detail_groups"]["sum_fields"], [])

	def test_mixed_currencies_are_not_added_and_empty_groups_are_combined(self):
		from frappe.core.doctype.doctype.test_doctype import new_doctype

		doc = new_doctype(
			title="Report Grouping Test",
			fields=[
				{"fieldname": "category", "label": "Category", "fieldtype": "Data"},
				{"fieldname": "currency", "label": "Currency", "fieldtype": "Data"},
				{"fieldname": "amount", "label": "Amount", "fieldtype": "Currency", "options": "currency"},
			],
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc_if_exists, "DocType", doc.name)
		for category, currency, amount in [(None, "USD", 10), ("", "CNY", 20), ("A", "USD", 30)]:
			record = frappe.get_doc(
				{"doctype": doc.name, "category": category, "currency": currency, "amount": amount}
			).insert(ignore_permissions=True)
			# Preserve a real SQL NULL rather than Frappe's default empty string.
			if category is None:
				frappe.db.set_value(doc.name, record.name, "category", None)
		frappe.local.form_dict = frappe._dict(
			doctype=doc.name,
			fields=["name", "category", "amount"],
			detail_group_by="category",
			page_length=1,
		)
		groups = get()["detail_groups"]["groups"]
		self.assertEqual(len(groups), 2)
		empty = next(group for group in groups if group["category"] == "")
		self.assertEqual(empty["_count"], 2)
		self.assertIsNone(empty["amount"])
		usd = next(group for group in groups if group["category"] == "A")
		self.assertEqual(usd["amount"], 30)
		self.assertEqual(usd["currency"], "USD")
		frappe.local.form_dict.detail_group_by = ["category", "currency"]
		groups = {tuple(group["_path"]): group for group in get()["detail_groups"]["groups"]}
		self.assertIsNone(groups[("",)]["amount"])
		self.assertEqual(groups[("", "USD")]["amount"], 10)
		self.assertEqual(groups[("", "CNY")]["amount"], 20)

	def test_export_accepts_the_detail_display_parameter(self):
		from csv import DictReader
		from io import StringIO

		from frappe.desk.reportview import export_query

		previous_response = frappe.local.response
		self.addCleanup(setattr, frappe.local, "response", previous_response)
		frappe.local.response = frappe._dict()
		frappe.local.form_dict.update(file_format_type="CSV", visible_names=["Report", "DocField"])
		export_query()
		rows = list(DictReader(StringIO(frappe.response.filecontent.decode("utf-8"))))
		self.assertEqual([row["ID"] for row in rows], ["Report", "DocField"])

	def test_nested_groups_have_independent_parent_and_child_totals(self):
		frappe.local.form_dict.detail_group_by = ["module", "istable"]
		result = get()
		self.assertEqual(len(result["values"]), 1)
		summary = result["detail_groups"]
		self.assertEqual(summary["fieldnames"], ["module", "istable"])
		groups = {tuple(group["_path"]): group for group in summary["groups"]}
		self.assertEqual(groups[("Core",)]["_count"], 3)
		self.assertEqual(groups[("Core",)]["max_attachments"], 60)
		self.assertEqual(groups[("Core", 0)]["max_attachments"], 50)
		self.assertEqual(groups[("Core", 1)]["max_attachments"], 10)
		self.assertEqual(groups[("Core", 0)]["_level"], 1)

	def test_reordering_fields_changes_the_hierarchy_and_keeps_paths_distinct(self):
		frappe.local.form_dict.detail_group_by = '["istable", "module"]'
		summary = get()["detail_groups"]
		self.assertEqual(summary["fieldnames"], ["istable", "module"])
		groups = {tuple(group["_path"]): group for group in summary["groups"]}
		self.assertEqual(set(groups), {(0,), (1,), (0, "Core"), (1, "Core")})
		self.assertEqual(groups[(0, "Core")]["_count"], 2)
		self.assertEqual(groups[(1, "Core")]["_count"], 1)

	def test_three_levels_and_filtered_leaf_loading(self):
		frappe.local.form_dict.detail_group_by = ["module", "istable", "name"]
		summary = get()["detail_groups"]
		self.assertEqual(len(summary["groups"]), 6)
		frappe.local.form_dict.filters.extend([["module", "=", "Core"], ["istable", "=", 0]])
		frappe.local.form_dict.page_length = 100
		result = get()
		self.assertEqual({row[0] for row in result["values"]}, {"Report", "User"})
		self.assertEqual(result["detail_groups"]["groups"][0]["max_attachments"], 50)

	def test_all_levels_are_validated_and_duplicate_levels_are_rejected(self):
		for fields in [["module", "module"], ["module", "`tabUser`.`email`"], ["module", "missing_field"]]:
			with self.subTest(fields=fields):
				frappe.local.form_dict.detail_group_by = fields
				with self.assertRaises(frappe.DataError):
					get()
		_validate_group_by_args(
			{"mode": "detail", "group_by": "module", "group_by_fields": ["module", "istable"]}, "DocType"
		)
		with self.assertRaises(frappe.DataError):
			_validate_group_by_args(
				{"mode": "detail", "group_by": "module", "group_by_fields": ["module", "module"]}, "DocType"
			)
