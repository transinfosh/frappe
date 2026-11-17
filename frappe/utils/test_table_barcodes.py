# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.print_format_generator import PrintFormatGenerator, get_qr_code
from frappe.utils.typst_emitter import typst_blockers


class TestTableBarcodes(IntegrationTestCase):
	def generator(self, barcode_format="QR", values=("ITEM-001", "ITEM-002"), **options):
		# Unsaved Contact rows exercise the real child metadata without business fixtures.
		doc = frappe.get_doc({"doctype": "Contact", "first_name": "Barcode preview"})
		for value in values:
			doc.append("email_ids", {"email_id": value})
		column = {
			"fieldname": "is_primary",
			"fieldtype": "Check",
			"label": "Item code",
			"barcode_format": barcode_format,
			"barcode_field": "email_id",
			**options,
		}
		table = {"fieldtype": "Table", "fieldname": "email_ids", "table_columns": [column]}
		layout = {"sections": [{"columns": [{"fields": [table]}]}]}
		pf = frappe.get_doc(
			{
				"doctype": "Print Format",
				"doc_type": "Contact",
				"print_format_builder_beta": 1,
				"pdf_generator": "chrome",
				"page_number": "Hide",
				"font_size": 14,
				"format_data": json.dumps(layout),
				"margin_left": 10,
				"margin_right": 10,
				"margin_top": 10,
				"margin_bottom": 10,
			}
		)
		return PrintFormatGenerator(pf, doc, no_letterhead=True)

	def column(self, generator):
		return generator.layout["sections"][0]["columns"][0]["fields"][0]["table_columns"][0]

	def test_qr_uses_each_rows_selected_source_without_changing_data(self):
		generator = self.generator()
		cells = self.column(generator)["_barcode_cells"]
		self.assertEqual(cells["1"]["qr"], get_qr_code("ITEM-001"))
		self.assertEqual(cells["2"]["qr"], get_qr_code("ITEM-002"))
		self.assertNotEqual(cells["1"]["qr"], cells["2"]["qr"])
		self.assertIn(cells["2"]["qr"], generator.get_html_preview())
		self.assertEqual(generator.doc.email_ids[0].email_id, "ITEM-001")
		self.assertFalse(generator.doc.email_ids[0].is_primary)

	def test_empty_destination_does_not_prune_barcode_column(self):
		generator = self.generator(values=("ITEM-001",))
		self.assertIn("data:image/svg+xml;base64", generator.get_html_preview())
		self.assertEqual(len(self.column(generator)["_barcode_cells"]), 1)

	def test_empty_values_and_zero(self):
		generator = self.generator(values=("", None, 0))
		cells = self.column(generator)["_barcode_cells"]
		self.assertNotIn("1", cells)
		self.assertNotIn("2", cells)
		self.assertEqual(cells["3"]["value"], "0")

	def test_barcodes_escape_values_and_keep_options(self):
		generator = self.generator(
			"CODE128", values=('ITEM-"<001>',), barcode_show_text=False, barcode_width=9999
		)
		html = generator.get_html_preview()
		self.assertIn('data-barcode-value="ITEM-&#34;&lt;001&gt;"', html)
		self.assertIn("width:300px", html)
		self.assertIn("CODE128", html)
		self.assertIn("false", html)
		self.assertEqual(self.column(generator)["_barcode_cells"]["1"]["value"], 'ITEM-"<001>')

	def test_invalid_values_and_format(self):
		for barcode_format in ("CODE39", "CODE128"):
			generator = self.generator(barcode_format, values=("中文物料",))
			self.assertIn("error", self.column(generator)["_barcode_cells"]["1"])
			self.assertNotIn('data-barcode-value="', generator.get_html_preview())
		with self.assertRaises(frappe.ValidationError):
			self.generator("BAD")

	def test_source_permission_is_checked(self):
		original = PrintFormatGenerator.has_field_access

		def allowed(doc, meta, fieldname, source_fieldname=None):
			return fieldname != "email_id" and original(doc, meta, fieldname, source_fieldname)

		with patch.object(PrintFormatGenerator, "has_field_access", side_effect=allowed):
			generator = self.generator()
		self.assertEqual(generator.layout["sections"][0]["columns"][0]["fields"][0]["table_columns"], [])
		self.assertNotIn("data:image/svg+xml;base64", generator.get_html_preview())

	def test_qr_capacity_overflow_keeps_other_rows_and_text_printable(self):
		from bs4 import BeautifulSoup

		from frappe.utils.typst_emitter import TypstEmitter

		for value in ("a" * 2000, "中" * 1000, "a" * 2001):
			with self.subTest(value_length=len(value)):
				generator = self.generator(values=(value, "ITEM-002"))
				column = self.column(generator)
				cells = column["_barcode_cells"]
				self.assertNotIn("1", cells)
				self.assertIn("qr", cells["2"])
				self.assertEqual(generator.doc.email_ids[0].email_id, value)
				self.assertEqual(TypstEmitter(generator)._table_cell(generator.doc.email_ids[0], column), "")
				table = generator.layout["sections"][0]["columns"][0]["fields"][0]
				table["table_columns"].append(
					{"fieldname": "email_id", "fieldtype": "Data", "label": "Source"}
				)
				html = generator.get_html_preview()
				first_cell = BeautifulSoup(html, "html.parser").select(".child-table tbody tr")[0].find("td")
				self.assertEqual(first_cell.get_text(strip=True), "")
				self.assertIsNone(first_cell.find("img"))
				self.assertNotIn(frappe._("Invalid value for {0}").format("QR"), html)
				self.assertIn(cells["2"]["qr"], html)
				self.assertIn("ITEM-002", html)

	def test_text_fallback_and_typst_gate(self):
		from frappe.utils.typst_emitter import TypstEmitter
		from frappe.utils.weasyprint_legacy import legacy_blockers

		generator = self.generator("")
		self.assertNotIn('data-barcode-value="', generator.get_html_preview())
		qr = self.generator()
		self.assertEqual(typst_blockers(qr.print_format, qr.layout), [])
		emitter = TypstEmitter(qr)
		self.assertIn("#image(", emitter._table_cell(qr.doc.email_ids[0], self.column(qr)))
		self.assertIn("Table column barcodes", legacy_blockers(qr.print_format, qr.layout))
		barcode = self.generator("CODE128")
		self.assertIn("Barcode that is not a QR code", typst_blockers(barcode.print_format, barcode.layout))
