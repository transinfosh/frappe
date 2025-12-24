import json

from werkzeug.routing import Rule

import frappe
from frappe import _
from frappe.model.base_document import RESERVED_KEYWORDS
from frappe.utils.data import sbool


def document_list(doctype: str):
	if frappe.form_dict.get("fields"):
		frappe.form_dict["fields"] = json.loads(frappe.form_dict["fields"])

	# set limit of records for frappe.get_list
	frappe.form_dict.setdefault(
		"limit_page_length",
		frappe.form_dict.limit or frappe.form_dict.limit_page_length or 20,
	)

	# convert strings to native types - only as_dict and debug accept bool
	for param in ["as_dict", "debug"]:
		param_val = frappe.form_dict.get(param)
		if param_val is not None:
			frappe.form_dict[param] = sbool(param_val)

	# evaluate frappe.get_list
	return frappe.call(frappe.client.get_list, doctype, **frappe.form_dict)


def handle_rpc_call(method: str):
	import frappe.handler

	method = method.split("/")[0]  # for backward compatiblity

	frappe.form_dict.cmd = method
	return frappe.handler.handle()


def create_doc(doctype: str):
	data = get_request_form_data()
	data.pop("doctype", None)
	if (id := data.get("id")) and isinstance(id, str):
		frappe.flags.api_id_set = True
	return frappe.new_doc(doctype, **data).insert()


def update_doc(doctype: str, id: str):
	data = get_request_form_data()

	doc = frappe.get_doc(doctype, id, for_update=True)
	if "flags" in data:
		del data["flags"]

	# 针对子表数据的更新处理
	doc_table_fieldnames = doc._table_fieldnames
	for key in doc_table_fieldnames:
		if key not in data:
			continue  # 如果请求数据中没有该子表，则跳过

		exist_list_dict = {str(item.id): item for item in doc.get(key)}
		for data_item in data.get(key):
			data_item_id = data_item.get("id")
			if data_item_id is None:
				continue  # 新增的行，跳过后续更新逻辑

			data_item_id = str(data_item_id)
			if data_item_id not in exist_list_dict:
				data_item.set("id", None)  # 如果ID不存在于现有列表中，设置为None以新增
				continue

			# 更新记录
			exist_item = exist_list_dict.get(data_item_id)
			for fieldname in list(data_item.keys()):  # 删除保留字字段
				if fieldname in RESERVED_KEYWORDS:
					del data_item[fieldname]

			for fieldname, value in exist_item.as_dict().items():
				if fieldname not in RESERVED_KEYWORDS and fieldname not in data_item:
					data_item[fieldname] = value

	doc.update(data)
	doc.save()

	# check for child table doctype
	if doc.get("parenttype"):
		frappe.get_doc(doc.parenttype, doc.parent).save()

	return doc


def delete_doc(doctype: str, id: str):
	# TODO: child doc handling
	frappe.delete_doc(doctype, id, ignore_missing=False)
	frappe.response.http_status_code = 202
	return "ok"


def read_doc(doctype: str, id: str):
	# Backward compatiblity
	if "run_method" in frappe.form_dict:
		return execute_doc_method(doctype, id)

	doc = frappe.get_doc(doctype, id)
	doc.check_permission("read")
	doc.apply_fieldlevel_read_permissions()
	return doc


def execute_doc_method(doctype: str, id: str, method: str | None = None):
	method = method or frappe.form_dict.pop("run_method")
	doc = frappe.get_doc(doctype, id)
	doc.is_whitelisted(method)

	if frappe.request.method == "GET":
		doc.check_permission("read")
		return doc.run_method(method, **frappe.form_dict)

	elif frappe.request.method == "POST":
		doc.check_permission("write")
		return doc.run_method(method, **frappe.form_dict)


def get_request_form_data():
	if frappe.form_dict.data is None:
		data = frappe.safe_decode(frappe.request.get_data())
	else:
		data = frappe.form_dict.data

	try:
		return frappe.parse_json(data)
	except ValueError:
		return frappe.form_dict


url_rules = [
	Rule("/method/<path:method>", endpoint=handle_rpc_call),
	Rule("/resource/<doctype>", methods=["GET"], endpoint=document_list),
	Rule("/resource/<doctype>", methods=["POST"], endpoint=create_doc),
	Rule("/resource/<doctype>/<path:id>/", methods=["GET"], endpoint=read_doc),
	Rule("/resource/<doctype>/<path:id>/", methods=["PUT"], endpoint=update_doc),
	Rule("/resource/<doctype>/<path:id>/", methods=["DELETE"], endpoint=delete_doc),
	Rule("/resource/<doctype>/<path:id>/", methods=["POST"], endpoint=execute_doc_method),
]
