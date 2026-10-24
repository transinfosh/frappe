# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

"""Resolve `show_title_field_in_link` titles for sets of link values."""

import frappe
from frappe.model import get_permitted_fields
from frappe.utils import create_batch

TITLE_BATCH_SIZE = 500


def get_link_title_field(doctype: str) -> str | None:
	"""Configured title field; child-table permissions are checked against each row's parent."""
	meta = frappe.get_meta(doctype)
	if not (meta.show_title_field_in_link and meta.title_field):
		return None

	title_field = meta.title_field.strip()
	if title_field == "name":
		return None
	if meta.istable:
		return title_field
	if not frappe.has_permission(doctype, "select"):
		return None
	if title_field not in get_permitted_fields(doctype, ignore_virtual=True):
		return None

	return title_field


def get_link_titles(doctype: str, title_field: str, names: set[str]) -> dict[str, str]:
	"""Titles of the readable documents among `names`, keyed by document name."""
	names = {name for name in names if not _is_empty_link_value(name)}
	if not names:
		return {}
	if frappe.get_meta(doctype).istable:
		return _get_child_link_titles(doctype, title_field, names)

	titles = {}
	for names_batch in create_batch(list(names), TITLE_BATCH_SIZE):
		rows = frappe.get_list(
			doctype,
			filters={"name": ("in", names_batch)},
			fields=["name", title_field],
			limit=len(names_batch),
		)
		titles.update({row.name: row.get(title_field) for row in rows})
	return titles


def _get_child_link_titles(doctype: str, title_field: str, names: set[str]) -> dict[str, str]:
	titles = {}
	for name in names:
		try:
			doc = frappe.get_lazy_doc(doctype, name)
			if not frappe.has_permission(doctype, doc=doc):
				continue
			if title_field not in get_permitted_fields(
				doctype, parenttype=doc.parenttype, ignore_virtual=True
			):
				continue
			titles[doc.name] = doc.get(title_field)
		except frappe.DoesNotExistError:
			frappe.clear_last_message()
	return titles


def send_link_titles(link_titles: dict[str, str]):
	"""Append link titles dict in `frappe.local.response`."""
	if "_link_titles" not in frappe.local.response:
		frappe.local.response["_link_titles"] = {}

	frappe.local.response["_link_titles"].update(link_titles)


def get_report_link_titles(columns, rows) -> dict[str, str]:
	"""Titles for the Link values in `rows`, keyed `doctype::name` for the client cache."""
	titles = {}
	names_by_doctype = get_link_names_by_doctype(columns or [], rows or [])
	for doctype, names in names_by_doctype.items():
		title_field = get_link_title_field(doctype)
		if not title_field:
			continue
		for name, title in get_link_titles(doctype, title_field, names).items():
			titles[f"{doctype}::{name}"] = title
	return titles


def get_link_names_by_doctype(columns, rows) -> dict[str, set]:
	"""Distinct non-empty values of every Link column, grouped by the doctype they link to."""
	link_columns = [
		(index, column["fieldname"], column["options"])
		for index, column in enumerate(columns)
		if isinstance(column, dict)
		and column.get("fieldtype") == "Link"
		and column.get("fieldname")
		and column.get("options")
	]

	names_by_doctype = {}
	for row in rows:
		for index, fieldname, doctype in link_columns:
			# report rows are dicts, except in the prepared report path where they stay lists
			if isinstance(row, dict):
				name = row.get(fieldname)
			else:
				name = row[index] if index < len(row) else None
			if not _is_empty_link_value(name):
				names_by_doctype.setdefault(doctype, set()).add(name)
	return names_by_doctype


def _is_empty_link_value(value) -> bool:
	return value is None or (isinstance(value, str) and value in {"", "null", "undefined"})
