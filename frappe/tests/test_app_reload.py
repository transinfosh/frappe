# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import os
from unittest.mock import patch

from watchdog.events import FileModifiedEvent
from werkzeug._reloader import WatchdogReloaderLoop

from frappe import app
from frappe.tests import UnitTestCase


class TestDevelopmentReload(UnitTestCase):
	def test_upload_archives_do_not_interrupt_requests_but_source_edits_reload(self):
		sites_path = os.path.abspath(".")
		with (
			patch.object(app, "application"),
			patch.object(app, "_site"),
			patch.object(app, "_sites_path"),
			patch.dict(os.environ, {"NO_STATICS": "1"}),
			patch("werkzeug.serving.run_simple") as run_simple,
		):
			app.serve(sites_path=sites_path)
		patterns = run_simple.call_args.kwargs["exclude_patterns"]
		reloader = WatchdogReloaderLoop(exclude_patterns=patterns)
		for relative_path in (
			"development.localhost/private/files/.temp-quality-mobile.zip",
			"test.localhost/private/files/h5-packages/version.zip",
			"test.localhost/public/files/website.zip",
		):
			with self.subTest(path=relative_path):
				reloader.should_reload.clear()
				reloader.event_handler.dispatch(FileModifiedEvent(os.path.join(sites_path, relative_path)))
				self.assertFalse(reloader.should_reload.is_set())
		for relative_path in ("../apps/frappe/frappe/handler.py", "../apps/frappe/dependencies.zip"):
			with self.subTest(source=relative_path):
				reloader.should_reload.clear()
				reloader.event_handler.dispatch(FileModifiedEvent(os.path.abspath(relative_path)))
				self.assertTrue(reloader.should_reload.is_set())
