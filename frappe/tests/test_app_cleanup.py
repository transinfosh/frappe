from unittest.mock import Mock, patch

import pytest

from frappe.app import after_response_wrapper
from frappe.tests import UnitTestCase


class TestAfterResponseWrapper(UnitTestCase):
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

		with (
			patch("frappe.rate_limiter.update", side_effect=RuntimeError("cleanup failed")),
			patch("frappe.request", Mock(after_response=Mock())),
			patch("frappe.destroy") as destroy,
		):
			response = after_response_wrapper(application)({}, lambda *_args: None)
			with pytest.raises(RuntimeError, match="cleanup failed"):
				response.close()

		destroy.assert_called_once_with()

	def test_destroys_context_when_response_iterator_creation_raises(self):
		class FailingIterable:
			def __iter__(self):
				raise RuntimeError("iterator creation failed")

		with (
			patch("frappe.request", Mock(after_response=Mock())),
			patch("frappe.destroy") as destroy,
			pytest.raises(RuntimeError, match="iterator creation failed"),
		):
			after_response_wrapper(lambda *_args: FailingIterable())({}, lambda *_args: None)

		destroy.assert_called_once_with()

	def test_closes_request_context_only_once(self):
		with (
			patch("frappe.rate_limiter.update") as update_rate_limit,
			patch("frappe.recorder.dump") as dump_recording,
			patch("frappe.request", Mock(after_response=Mock())) as request,
			patch("frappe.destroy") as destroy,
		):
			response = after_response_wrapper(lambda *_args: [b"ok"])({}, lambda *_args: None)
			response.close()
			response.close()

		update_rate_limit.assert_called_once_with()
		dump_recording.assert_called_once_with()
		request.after_response.run.assert_called_once_with()
		destroy.assert_called_once_with()

	def test_preserves_cleanup_error_when_destroy_also_raises(self):
		with (
			patch("frappe.rate_limiter.update", side_effect=RuntimeError("cleanup failed")),
			patch("frappe.request", Mock(after_response=Mock())),
			patch("frappe.destroy", side_effect=RuntimeError("destroy failed")) as destroy,
		):
			response = after_response_wrapper(lambda *_args: [b"ok"])({}, lambda *_args: None)
			with pytest.raises(RuntimeError, match="cleanup failed"):
				response.close()

		destroy.assert_called_once_with()

	def test_destroys_context_when_response_close_raises(self):
		class FailingCloseIterable:
			def __iter__(self):
				return iter((b"ok",))

			def close(self):
				raise RuntimeError("response close failed")

		with (
			patch("frappe.request", Mock(after_response=Mock())),
			patch("frappe.destroy") as destroy,
		):
			response = after_response_wrapper(lambda *_args: FailingCloseIterable())({}, lambda *_args: None)
			with pytest.raises(RuntimeError, match="response close failed"):
				response.close()

		destroy.assert_called_once_with()

	def test_destroys_context_when_after_response_callback_raises(self):
		after_response = Mock()
		after_response.run.side_effect = RuntimeError("after response failed")

		with (
			patch("frappe.rate_limiter.update"),
			patch("frappe.recorder.dump"),
			patch("frappe.request", Mock(after_response=after_response)),
			patch("frappe.destroy") as destroy,
		):
			response = after_response_wrapper(lambda *_args: [b"ok"])({}, lambda *_args: None)
			with pytest.raises(RuntimeError, match="after response failed"):
				response.close()

		destroy.assert_called_once_with()
