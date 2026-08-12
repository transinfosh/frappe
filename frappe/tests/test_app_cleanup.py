from unittest.mock import Mock, patch

import pytest

import frappe
from frappe.app import after_response_wrapper
from frappe.tests import UnitTestCase
from frappe.utils import CallbackManager


class TestAfterResponseWrapper(UnitTestCase):
	def setUp(self):
		super().setUp()
		self.update_rate_limit = Mock()
		self.dump_recording = Mock()
		self.after_response = CallbackManager()
		self.after_response_callback = Mock()
		self.after_response.add(self.after_response_callback)
		self.enterContext(
			patch(
				"frappe.app.DEFAULT_AFTER_RESPONSE_CALLBACKS", (self.update_rate_limit, self.dump_recording)
			)
		)
		self.enterContext(
			patch.object(frappe.local, "request", Mock(after_response=self.after_response), create=True)
		)
		self.logger = self.enterContext(patch("frappe.logger")).return_value

	def test_destroys_context_when_application_raises(self):
		def failing_application(_environ, _start_response):
			raise RuntimeError("request failed")

		with patch("frappe.destroy") as destroy, pytest.raises(RuntimeError, match="request failed"):
			after_response_wrapper(failing_application)({}, lambda *_args: None)

		destroy.assert_called_once_with()

	def test_preserves_application_error_when_destroy_also_raises(self):
		def failing_application(_environ, _start_response):
			raise RuntimeError("request failed")

		with (
			patch("frappe.destroy", side_effect=RuntimeError("destroy failed")) as destroy,
			pytest.raises(RuntimeError, match="request failed"),
		):
			after_response_wrapper(failing_application)({}, lambda *_args: None)

		destroy.assert_called_once_with()

	def test_destroys_context_when_cleanup_callback_raises(self):
		def application(_environ, _start_response):
			return [b"ok"]

		self.update_rate_limit.side_effect = RuntimeError("cleanup failed")
		with patch("frappe.destroy") as destroy:
			response = after_response_wrapper(application)({}, lambda *_args: None)
			response.close()

		self.dump_recording.assert_called_once_with()
		self.after_response_callback.assert_called_once_with()
		self.logger.error.assert_called_once()
		destroy.assert_called_once_with()

	def test_destroys_context_when_response_iterator_creation_raises(self):
		class FailingIterable:
			def __iter__(self):
				raise RuntimeError("iterator creation failed")

		with (
			patch("frappe.destroy") as destroy,
			pytest.raises(RuntimeError, match="iterator creation failed"),
		):
			after_response_wrapper(lambda *_args: FailingIterable())({}, lambda *_args: None)

		destroy.assert_called_once_with()

	def test_closes_request_context_only_once(self):
		with patch("frappe.destroy") as destroy:
			response = after_response_wrapper(lambda *_args: [b"ok"])({}, lambda *_args: None)
			response.close()
			response.close()

		self.update_rate_limit.assert_called_once_with()
		self.dump_recording.assert_called_once_with()
		self.after_response_callback.assert_called_once_with()
		destroy.assert_called_once_with()

	def test_preserves_fatal_callback_error_when_destroy_also_raises(self):
		self.update_rate_limit.side_effect = SystemExit("cleanup failed")
		with patch("frappe.destroy", side_effect=RuntimeError("destroy failed")) as destroy:
			response = after_response_wrapper(lambda *_args: [b"ok"])({}, lambda *_args: None)
			with pytest.raises(SystemExit, match="cleanup failed"):
				response.close()

		destroy.assert_called_once_with()

	def test_destroys_context_when_response_close_raises(self):
		class FailingCloseIterable:
			def __iter__(self):
				return iter((b"ok",))

			def close(self):
				raise RuntimeError("response close failed")

		with patch("frappe.destroy") as destroy:
			response = after_response_wrapper(lambda *_args: FailingCloseIterable())({}, lambda *_args: None)
			with pytest.raises(RuntimeError, match="response close failed"):
				response.close()

		destroy.assert_called_once_with()

	def test_destroys_context_when_after_response_callback_raises(self):
		self.after_response_callback.side_effect = RuntimeError("after response failed")
		later_callback = Mock()
		self.after_response.add(later_callback)

		with patch("frappe.destroy") as destroy:
			response = after_response_wrapper(lambda *_args: [b"ok"])({}, lambda *_args: None)
			response.close()

		later_callback.assert_called_once_with()
		self.logger.error.assert_called_once()
		destroy.assert_called_once_with()
