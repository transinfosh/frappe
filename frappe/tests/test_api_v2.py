import typing
from random import choice
from unittest.mock import patch

import requests

import frappe
from frappe.installer import update_site_config
from frappe.tests.test_api import FrappeAPITestCase, suppress_stdout
from frappe.tests.utils import toggle_test_mode, whitelist_for_tests

authorization_token = None


resource_key = {
	"": "resource",
	"v1": "resource",
	"v2": "document",
}


class TestResourceAPIV2(FrappeAPITestCase):
	version = "v2"
	DOCTYPE = "ToDo"
	GENERATED_DOCUMENTS: typing.ClassVar[list] = []

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for _ in range(20):
			doc = frappe.get_doc({"doctype": "ToDo", "description": frappe.mock("paragraph")}).insert()
			cls.GENERATED_DOCUMENTS = []
			cls.GENERATED_DOCUMENTS.append(doc.name)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.db.commit()
		for name in cls.GENERATED_DOCUMENTS:
			frappe.delete_doc_if_exists(cls.DOCTYPE, name)
		frappe.db.commit()

	def test_unauthorized_call_v2(self):
		# test 1: fetch documents without auth
		response = requests.get(self.resource("User"))
		self.assertEqual(response.status_code, 403)

	def test_get_list_v2(self):
		# test 2: fetch documents without params
		response = self.get(self.resource(self.DOCTYPE), {"sid": self.sid})
		self.assertEqual(response.status_code, 200)
		self.assertIsInstance(response.json, dict)
		self.assertIn("data", response.json)

	def test_get_list_limit_v2(self):
		# test 3: fetch data with limit
		response = self.get(self.resource(self.DOCTYPE), {"sid": self.sid, "limit": 2})
		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(response.json["data"]), 2)

	def test_get_list_dict_v2(self):
		# test 4: fetch response as (not) dict
		response = self.get(self.resource(self.DOCTYPE), {"sid": self.sid, "as_dict": True})
		json = frappe._dict(response.json)
		self.assertEqual(response.status_code, 200)
		self.assertIsInstance(json.data, list)
		self.assertIsInstance(json.data[0], dict)

		response = self.get(self.resource(self.DOCTYPE), {"sid": self.sid, "as_dict": False})
		json = frappe._dict(response.json)
		self.assertEqual(response.status_code, 200)
		self.assertIsInstance(json.data, list)
		self.assertIsInstance(json.data[0], list)

	def test_get_list_fields_v2(self):
		# test 6: fetch response with fields
		response = self.get(self.resource(self.DOCTYPE), {"sid": self.sid, "fields": '["description"]'})
		self.assertEqual(response.status_code, 200)
		json = frappe._dict(response.json)
		self.assertIn("description", json.data[0])

	def test_create_document_v2(self):
		data = {"description": frappe.mock("paragraph"), "sid": self.sid}
		response = self.post(self.resource(self.DOCTYPE), data)
		self.assertEqual(response.status_code, 200)
		docname = response.json["data"]["name"]
		self.assertIsInstance(docname, str)
		self.GENERATED_DOCUMENTS.append(docname)

	def test_copy_document_v2(self):
		doc = frappe.get_doc(self.DOCTYPE, self.GENERATED_DOCUMENTS[0])

		# disabled temporarily to assert that `docstatus` is not copied outside of tests
		toggle_test_mode(False)
		try:
			response = self.get(self.resource(self.DOCTYPE, doc.name, "copy"))
		finally:
			toggle_test_mode(True)

		self.assertEqual(response.status_code, 200)
		data = response.json["data"]

		self.assertEqual(data["doctype"], self.DOCTYPE)
		self.assertEqual(data["description"], doc.description)
		self.assertEqual(data["status"], doc.status)
		self.assertEqual(data["priority"], doc.priority)

		self.assertNotIn("name", data)
		self.assertNotIn("creation", data)
		self.assertNotIn("modified", data)
		self.assertNotIn("modified_by", data)
		self.assertNotIn("owner", data)
		self.assertNotIn("docstatus", data)

	def test_delete_document_v2(self):
		doc_to_delete = choice(self.GENERATED_DOCUMENTS)
		response = self.delete(self.resource(self.DOCTYPE, doc_to_delete), data={"sid": self.sid})
		self.assertEqual(response.status_code, 202)
		self.assertDictEqual(response.json, {"data": "ok"})

		response = self.get(self.resource(self.DOCTYPE, doc_to_delete))
		self.assertEqual(response.status_code, 404)
		self.GENERATED_DOCUMENTS.remove(doc_to_delete)

	def test_execute_doc_method_v2(self):
		response = self.get(self.resource("Website Theme", "Standard", "method", "get_apps"))
		self.assertEqual(response.json["data"][0]["name"], "frappe")

	def test_execute_doc_method_v2_validates_http_method(self):
		doc = frappe.get_doc("Website Theme", "Standard")
		method = getattr(doc.get_apps, "__func__", doc.get_apps)

		with (
			patch.dict(frappe.allowed_http_methods_for_whitelisted_func, {method: ["POST"]}),
			suppress_stdout(),
		):
			response = self.get(
				self.resource("Website Theme", "Standard", "method", "get_apps"), {"sid": self.sid}
			)

		self.assertEqual(response.status_code, 403)

	def test_update_document_v2(self):
		generated_desc = frappe.mock("paragraph")
		data = {"description": generated_desc, "sid": self.sid}
		random_doc = choice(self.GENERATED_DOCUMENTS)

		response = self.patch(self.resource(self.DOCTYPE, random_doc), data=data)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json["data"]["description"], generated_desc)

		response = self.get(self.resource(self.DOCTYPE, random_doc))
		self.assertEqual(response.json["data"]["description"], generated_desc)

	def test_delete_document_non_existing_v2(self):
		non_existent_doc = frappe.generate_hash(length=12)
		with suppress_stdout():
			response = self.delete(self.resource(self.DOCTYPE, non_existent_doc))
		self.assertEqual(response.status_code, 404)
		self.assertEqual(response.json["errors"][0]["type"], "DoesNotExistError")
		# 404s dont return exceptions
		self.assertFalse(response.json["errors"][0].get("exception"))


class TestPatchDocumentAPIV2(FrappeAPITestCase):
	version = "v2"

	def setUp(self):
		super().setUp()
		self.event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "PATCH original subject",
				"starts_on": "2026-08-27 09:00:00",
				"event_type": "Public",
				"event_participants": [
					{
						"reference_doctype": "DocType",
						"reference_docname": "Event",
						"email": "original@example.com",
					},
					{
						"reference_doctype": "DocType",
						"reference_docname": "ToDo",
						"email": "second@example.com",
					},
				],
				"notifications": [{"type": "Email", "before": 1, "interval": "Day"}],
			}
		).insert()
		self.events_to_delete = [self.event.name]
		self.child_rows_to_delete = []
		frappe.db.commit()

	def tearDown(self):
		for name in self.events_to_delete:
			frappe.delete_doc_if_exists("Event", name, force=True)
		for name in self.child_rows_to_delete:
			frappe.db.delete("Event Participants", {"name": name})
		frappe.db.commit()
		super().tearDown()

	def patch_event(self, data):
		return self.patch(self.resource("Event", self.event.name), {"sid": self.sid, **data})

	def test_patch_updates_only_provided_parent_field(self):
		response = self.patch_event({"status": "Closed"})

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json["data"]["status"], "Closed")
		self.assertEqual(response.json["data"]["subject"], "PATCH original subject")

	def test_patch_explicit_null_clears_optional_parent_field(self):
		self.event.description = "Original description"
		self.event.save()
		frappe.db.commit()

		response = self.patch_event({"description": None})

		self.assertEqual(response.status_code, 200)
		self.assertIsNone(response.json["data"]["description"])

	def test_patch_omitted_child_table_remains_unchanged(self):
		original_rows = [row.as_dict() for row in self.event.event_participants]

		response = self.patch_event({"status": "Closed"})

		self.assertEqual(response.status_code, 200)
		patched_rows = response.json["data"]["event_participants"]
		self.assertEqual([row["name"] for row in patched_rows], [row["name"] for row in original_rows])
		self.assertEqual([row["email"] for row in patched_rows], [row["email"] for row in original_rows])

	def test_patch_handles_multiple_child_tables_independently(self):
		participant = self.event.event_participants[0]
		notification = self.event.notifications[0]
		response = self.patch_event(
			{
				"event_participants": [{"name": participant.name, "email": "participant@example.com"}],
				"notifications": [{"name": notification.name, "before": 3}],
			}
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json["data"]["event_participants"][0]["reference_docname"], "Event")
		self.assertEqual(response.json["data"]["event_participants"][0]["email"], "participant@example.com")
		self.assertEqual(response.json["data"]["notifications"][0]["type"], "Email")
		self.assertEqual(response.json["data"]["notifications"][0]["before"], 3)

	def test_patch_existing_child_row_preserves_omitted_fields(self):
		row = self.event.event_participants[0]
		omitted_row = self.event.event_participants[1]

		response = self.patch_event(
			{"event_participants": [{"name": row.name, "email": "patched@example.com"}]}
		)

		self.assertEqual(response.status_code, 200)
		patched_row = response.json["data"]["event_participants"][0]
		self.assertEqual(patched_row["reference_doctype"], "DocType")
		self.assertEqual(patched_row["reference_docname"], "Event")
		self.assertEqual(patched_row["email"], "patched@example.com")
		self.assertFalse(frappe.db.exists("Event Participants", omitted_row.name))

	def test_patch_adds_child_row_without_name(self):
		response = self.patch_event(
			{
				"event_participants": [
					{
						"reference_doctype": "DocType",
						"reference_docname": "Event",
						"email": "new@example.com",
					}
				]
			}
		)

		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.json["data"]["event_participants"][0]["name"])
		self.assertEqual(response.json["data"]["event_participants"][0]["email"], "new@example.com")

	def test_patch_empty_child_table_deletes_all_rows(self):
		response = self.patch_event({"event_participants": []})

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json["data"]["event_participants"], [])
		self.assertEqual(
			frappe.db.count(
				"Event Participants", {"parent": self.event.name, "parentfield": "event_participants"}
			),
			0,
		)

	def test_patch_child_table_combines_update_add_delete_and_request_order(self):
		kept_row = self.event.event_participants[0]
		deleted_row = self.event.event_participants[1]
		response = self.patch_event(
			{
				"event_participants": [
					{
						"reference_doctype": "DocType",
						"reference_docname": "ToDo",
						"email": "new-first@example.com",
					},
					{"name": kept_row.name, "email": "kept-second@example.com"},
				]
			}
		)

		self.assertEqual(response.status_code, 200)
		rows = response.json["data"]["event_participants"]
		self.assertEqual([row["email"] for row in rows], ["new-first@example.com", "kept-second@example.com"])
		self.assertEqual([row["idx"] for row in rows], [1, 2])
		self.assertNotEqual(rows[0]["name"], kept_row.name)
		self.assertEqual(rows[1]["name"], kept_row.name)
		self.assertFalse(frappe.db.exists("Event Participants", deleted_row.name))

	def test_patch_rejects_duplicate_child_row_name(self):
		row = self.event.event_participants[0]

		with suppress_stdout():
			response = self.patch_event(
				{
					"event_participants": [
						{"name": row.name, "email": "first@example.com"},
						{"name": row.name, "email": "duplicate@example.com"},
					]
				}
			)

		self.assertEqual(response.status_code, 417)
		self.assertEqual(response.json["errors"][0]["type"], "ValidationError")
		self.assertIn("Duplicate child row", response.json["errors"][0]["message"])

	def test_patch_rejects_child_row_from_another_parent(self):
		other_event = frappe.copy_doc(self.event).insert()
		self.events_to_delete.append(other_event.name)
		frappe.db.commit()
		foreign_row = other_event.event_participants[0]

		with suppress_stdout():
			response = self.patch_event(
				{"event_participants": [{"name": foreign_row.name, "email": "stolen@example.com"}]}
			)

		self.assertEqual(response.status_code, 417)
		self.assertIn("does not belong", response.json["errors"][0]["message"])
		self.assertEqual(
			frappe.db.get_value("Event Participants", foreign_row.name, "email"), "original@example.com"
		)

	def test_patch_rejects_child_row_from_another_parentfield(self):
		foreign_row = frappe.copy_doc(self.event.event_participants[0])
		foreign_row.parent = self.event.name
		foreign_row.parenttype = "Event"
		foreign_row.parentfield = "notifications"
		foreign_row.insert()
		self.child_rows_to_delete.append(foreign_row.name)
		frappe.db.commit()

		with suppress_stdout():
			response = self.patch_event(
				{"event_participants": [{"name": foreign_row.name, "email": "moved@example.com"}]}
			)

		self.assertEqual(response.status_code, 417)
		self.assertIn("does not belong", response.json["errors"][0]["message"])
		self.assertEqual(
			frappe.db.get_value("Event Participants", foreign_row.name, "parentfield"), "notifications"
		)

	def test_patch_new_child_missing_mandatory_field_rolls_back_entire_request(self):
		with suppress_stdout():
			response = self.patch_event(
				{
					"status": "Closed",
					"event_participants": [{"email": "missing-required@example.com"}],
				}
			)

		self.assertEqual(response.status_code, 417)
		self.assertEqual(response.json["errors"][0]["type"], "MandatoryError")
		self.assertEqual(frappe.db.get_value("Event", self.event.name, "status"), "Open")
		self.assertEqual(
			frappe.db.count(
				"Event Participants", {"parent": self.event.name, "parentfield": "event_participants"}
			),
			2,
		)

	def test_patch_explicit_null_on_mandatory_child_field_fails(self):
		row = self.event.event_participants[0]

		with suppress_stdout():
			response = self.patch_event(
				{
					"event_participants": [
						{"name": row.name, "reference_docname": None, "email": "not-saved@example.com"}
					]
				}
			)

		self.assertEqual(response.status_code, 417)
		self.assertEqual(response.json["errors"][0]["type"], "MandatoryError")
		self.assertEqual(frappe.db.get_value("Event Participants", row.name, "reference_docname"), "Event")
		self.assertEqual(frappe.db.get_value("Event Participants", row.name, "email"), "original@example.com")

	def test_patch_rejects_internal_and_unknown_parent_fields(self):
		for fieldname, value in (
			("name", "OTHER-NAME"),
			("owner", "Guest"),
			("flags", {}),
			("unknown_internal", "value"),
		):
			with self.subTest(fieldname=fieldname), suppress_stdout():
				response = self.patch_event({fieldname: value})

			self.assertEqual(response.status_code, 417)
			self.assertEqual(response.json["errors"][0]["type"], "ValidationError")

	def test_patch_rejects_read_only_field(self):
		with suppress_stdout():
			response = self.patch_event({"google_meet_link": "https://example.com/meeting"})

		self.assertEqual(response.status_code, 417)
		self.assertIn("is read only", response.json["errors"][0]["message"])

	def test_patch_rejects_internal_child_fields(self):
		row = self.event.event_participants[0]

		with suppress_stdout():
			response = self.patch_event(
				{
					"event_participants": [
						{"name": row.name, "parent": "OTHER", "email": "ignored@example.com"}
					]
				}
			)

		self.assertEqual(response.status_code, 417)
		self.assertIn("cannot be updated", response.json["errors"][0]["message"])
		self.assertEqual(frappe.db.get_value("Event Participants", row.name, "email"), "original@example.com")

	def test_patch_rejects_invalid_child_table_value(self):
		with suppress_stdout():
			response = self.patch_event({"event_participants": {"email": "not-a-list@example.com"}})

		self.assertEqual(response.status_code, 417)
		self.assertIn("must be a list", response.json["errors"][0]["message"])

	def test_patch_rejects_invalid_child_row_value(self):
		with suppress_stdout():
			response = self.patch_event({"event_participants": ["not-an-object"]})

		self.assertEqual(response.status_code, 417)
		self.assertIn("must be an object", response.json["errors"][0]["message"])

	def test_patch_rejects_explicit_empty_child_row_name(self):
		for row_name in (None, "", []):
			with self.subTest(row_name=row_name), suppress_stdout():
				response = self.patch_event(
					{"event_participants": [{"name": row_name, "email": "new@example.com"}]}
				)

			self.assertEqual(response.status_code, 417)
			self.assertIn("must be a non-empty string", response.json["errors"][0]["message"])

	def test_patch_requires_write_permission(self):
		response = requests.patch(self.resource("Event", self.event.name), json={"status": "Closed"})

		self.assertEqual(response.status_code, 403)
		self.assertEqual(response.json()["errors"][0]["type"], "PermissionError")
		self.assertEqual(frappe.db.get_value("Event", self.event.name, "status"), "Open")

	def test_patch_response_matches_v2_document_update_shape(self):
		response = self.patch_event({"status": "Closed"})

		self.assertEqual(response.status_code, 200)
		self.assertEqual(set(response.json), {"data"})
		self.assertEqual(response.json["data"]["doctype"], "Event")
		self.assertEqual(response.json["data"]["name"], self.event.name)

	def test_put_keeps_full_child_replacement_semantics(self):
		row = self.event.event_participants[0]
		response = self.put(
			self.resource("Event", self.event.name),
			{
				"sid": self.sid,
				"event_participants": [
					{
						"name": row.name,
						"reference_doctype": "DocType",
						"reference_docname": "Event",
						"email": "put@example.com",
					}
				],
			},
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(response.json["data"]["event_participants"]), 1)
		self.assertEqual(response.json["data"]["event_participants"][0]["email"], "put@example.com")

	def test_put_keeps_rejecting_partial_existing_child_rows(self):
		row = self.event.event_participants[0]

		with suppress_stdout():
			response = self.put(
				self.resource("Event", self.event.name),
				{
					"sid": self.sid,
					"event_participants": [{"name": row.name, "email": "put-partial@example.com"}],
				},
			)

		self.assertEqual(response.status_code, 417)
		self.assertEqual(response.json["errors"][0]["type"], "MandatoryError")

	def test_v1_put_keeps_rejecting_partial_existing_child_rows(self):
		row = self.event.event_participants[0]
		path = f"{self.site_url}/api/resource/Event/{self.event.name}"

		with suppress_stdout():
			response = self.put(
				path,
				{
					"sid": self.sid,
					"event_participants": [{"name": row.name, "email": "v1-partial@example.com"}],
				},
			)

		self.assertEqual(response.status_code, 417)
		self.assertEqual(response.json["exc_type"], "MandatoryError")


class TestMethodAPIV2(FrappeAPITestCase):
	version = "v2"

	def setUp(self) -> None:
		self.post(self.method("login"), {"sid": self.sid})
		return super().setUp()

	def test_ping_v2(self):
		response = self.get(self.method("ping"))
		self.assertEqual(response.status_code, 200)
		self.assertIsInstance(response.json, dict)
		self.assertEqual(response.json["data"], "pong")

	def test_get_user_info_v2(self):
		# server-to-server only
		response = self.get(self.method("frappe.realtime.get_user_info"))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json.get("data"), {})

	def test_auth_cycle_v2(self):
		global authorization_token

		generate_admin_keys()
		user = frappe.get_doc("User", "Administrator")
		api_key, api_secret = user.api_key, user.get_password("api_secret")
		authorization_token = f"{api_key}:{api_secret}"
		response = self.get(self.method("frappe.auth.get_logged_user"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json["data"], "Administrator")

		authorization_token = None

	def test_404s_v2(self):
		response = self.get(self.get_path("rest"), {"sid": self.sid})
		self.assertEqual(response.status_code, 404)
		response = self.get(self.resource("User", "NonExistent@s.com"), {"sid": self.sid})
		self.assertEqual(response.status_code, 404)

	def test_shorthand_controller_methods_v2(self):
		shorthand_response = self.get(self.method("User", "get_all_roles"), {"sid": self.sid})
		self.assertIn("Website Manager", shorthand_response.json["data"])

		expanded_response = self.get(
			self.method("frappe.core.doctype.user.user.get_all_roles"), {"sid": self.sid}
		)
		self.assertEqual(expanded_response.data, shorthand_response.data)

	def test_logout_v2(self):
		self.post(self.method("logout"), {"sid": self.sid})
		response = self.get(self.method("ping"))
		self.assertFalse(response.request.cookies["sid"])

	def test_run_doc_method_in_memory_v2(self):
		dns = frappe.get_doc("Document Naming Settings")

		# Check that simple API can be called.
		response = self.get(
			self.method("run_doc_method"),
			{
				"sid": self.sid,
				"document": dns.as_dict(),
				"method": "get_transactions_and_prefixes",
			},
		)
		self.assertTrue(response.json["data"])
		self.assertGreaterEqual(len(response.json["docs"]), 1)

		# Call with known and unknown arguments, only known should get passed
		response = self.get(
			self.method("run_doc_method"),
			{
				"sid": self.sid,
				"document": dns.as_dict(),
				"method": "get_options",
				"kwargs": {"doctype": "Webhook", "unknown": "what"},
			},
		)
		self.assertEqual(response.status_code, 200)

	def test_logs_v2(self):
		method = "frappe.tests.test_api.test"

		expected_message = "Failed v2"
		response = self.get(self.method(method), {"sid": self.sid, "message": expected_message}).json

		self.assertIsInstance(response["messages"], list)
		self.assertEqual(response["messages"][0]["message"], expected_message)

		# Cause handled failured
		with suppress_stdout():
			response = self.get(
				self.method(method), {"sid": self.sid, "message": expected_message, "fail": True}
			).json
		self.assertIsInstance(response["errors"], list)
		self.assertEqual(response["errors"][0]["message"], expected_message)
		self.assertEqual(response["errors"][0]["type"], "ValidationError")
		self.assertIn("Traceback", response["errors"][0]["exception"])
		self.assertEqual(response["message"], expected_message)

		# Cause handled failured
		with suppress_stdout():
			response = self.get(
				self.method(method),
				{"sid": self.sid, "message": expected_message, "fail": True, "handled": False},
			).json

		self.assertIsInstance(response["errors"], list)
		self.assertEqual(response["errors"][0]["type"], "ZeroDivisionError")
		self.assertIn("Traceback", response["errors"][0]["exception"])
		self.assertEqual(response["message"], "Internal Server Error")

	def test_add_comment_v2(self):
		comment_txt = frappe.generate_hash()
		response = self.post(
			self.resource("User", "Administrator", "method", "add_comment"), {"text": comment_txt}
		).json
		self.assertEqual(response["data"]["content"], comment_txt)


class TestDocTypeAPIV2(FrappeAPITestCase):
	version = "v2"

	def setUp(self) -> None:
		self.post(self.method("login"), {"sid": self.sid})
		return super().setUp()

	def test_meta_v2(self):
		response = self.get(self.doctype_path("ToDo", "meta"))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json["data"]["name"], "ToDo")

	def test_count_v2(self):
		response = self.get(self.doctype_path("ToDo", "count"))
		self.assertIsInstance(response.json["data"], int)


class TestReadOnlyMode(FrappeAPITestCase):
	"""During migration if read only mode can be enabled.
	Test if reads work well and writes are blocked"""

	version = "v2"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		update_site_config("allow_reads_during_maintenance", 1)
		cls.addClassCleanup(update_site_config, "maintenance_mode", 0)
		update_site_config("maintenance_mode", 1)

	def test_reads_v2(self):
		response = self.get(self.resource("ToDo"), {"sid": self.sid})
		self.assertEqual(response.status_code, 200)
		self.assertIsInstance(response.json, dict)
		self.assertIsInstance(response.json["data"], list)

	def test_blocked_writes_v2(self):
		with suppress_stdout():
			response = self.post(
				self.resource("ToDo"), {"description": frappe.mock("paragraph"), "sid": self.sid}
			)
		self.assertEqual(response.status_code, 503)
		self.assertEqual(response.json["errors"][0]["type"], "InReadOnlyMode")


def generate_admin_keys():
	from frappe.core.doctype.user.user import generate_keys

	generate_keys("Administrator")
	frappe.db.commit()


@whitelist_for_tests()
def test(*, fail: int | bool = False, handled: int | bool = True, message: str = "Failed"):
	if fail:
		if handled:
			frappe.throw(message)
		else:
			1 / 0
	else:
		frappe.msgprint(message)
