# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

from frappe.tests import UnitTestCase
from frappe.gettext.extractors.utils import extract_messages_from_docfield
from frappe.utils.data import get_select_option_labels, get_select_options


class TestSelectOptions(UnitTestCase):
	def test_get_select_options_with_labeled_options(self):
		options = "\n1,Pending Inspection\n2,Approved\n3"

		self.assertEqual(get_select_options(options, options_has_label=True), ["", "1", "2", "3"])
		self.assertEqual(
			get_select_option_labels(options, options_has_label=True),
			["", "Pending Inspection", "Approved", "3"],
		)

	def test_get_select_options_removes_empty_values_when_requested(self):
		options = "\n  \n1,Pending Inspection\n2,Approved"

		self.assertEqual(
			get_select_options(options, options_has_label=True, remove_empty=True),
			["1", "2"],
		)
		self.assertEqual(
			get_select_option_labels(options, options_has_label=True, remove_empty=True),
			["Pending Inspection", "Approved"],
		)

	def test_get_select_option_labels_preserves_comma_when_labels_are_disabled(self):
		options = "New York, USA\nParis, France"

		self.assertEqual(
			get_select_option_labels(options, options_has_label=False, remove_empty=True),
			["New York, USA", "Paris, France"],
		)

	def test_get_select_option_labels_trims_labeled_values(self):
		options = "1, Pending Inspection\n2, Approved"

		self.assertEqual(
			get_select_option_labels(options, options_has_label=True, remove_empty=True),
			["Pending Inspection", "Approved"],
		)

	def test_get_select_options_trims_labeled_values(self):
		options = "1 ,Pending Inspection\n 2,Approved"

		self.assertEqual(
			get_select_options(options, options_has_label=True, remove_empty=True),
			["1", "2"],
		)

	def test_gettext_extractor_does_not_treat_zero_string_as_labeled_options(self):
		field = {
			"fieldname": "city",
			"fieldtype": "Select",
			"label": "City",
			"options": "New York, USA\nParis, France",
			"options_has_label": "0",
		}

		messages = [message for message, _context in extract_messages_from_docfield("Test DocType", field)]

		self.assertEqual(messages, ["City", "New York, USA", "Paris, France"])
