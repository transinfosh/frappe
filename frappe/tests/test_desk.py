from frappe.tests import UnitTestCase
from frappe.www.desk import get_app_splash_image, get_route_variants


class TestDeskSplashImage(UnitTestCase):
	def test_uses_fallback_without_matching_app(self):
		self.assertEqual(
			get_app_splash_image({"app_data": []}, "/desk", "/custom-splash.svg"),
			"/custom-splash.svg",
		)

	def test_matches_app_and_desk_route_variants(self):
		boot = {
			"app_data": [
				{
					"app_name": "example",
					"app_route": "/app/example",
					"app_logo_url": ["/old-logo.svg", "/example-logo.svg"],
				}
			]
		}

		for route in ("/app/example/report", "/desk/example/report"):
			with self.subTest(route=route):
				self.assertEqual(
					get_app_splash_image(boot, route, "/fallback.svg"),
					"/example-logo.svg",
				)

	def test_uses_longest_matching_route(self):
		boot = {
			"app_data": [
				{"app_name": "parent", "app_route": "/app/reports", "app_logo_url": "/parent.svg"},
				{
					"app_name": "child",
					"app_route": "/app/reports/sales",
					"app_logo_url": "/child.svg",
				},
			]
		}

		self.assertEqual(
			get_app_splash_image(boot, "/app/reports/sales/monthly", "/fallback.svg"),
			"/child.svg",
		)

	def test_uses_apps_screen_route_when_app_home_differs(self):
		boot = {
			"app_data": [{"app_name": "example", "app_route": "/app/home", "app_logo_url": "/example.svg"}]
		}
		app_screen_items = [{"name": "example", "route": "/app/example"}]

		self.assertEqual(
			get_app_splash_image(boot, "/app/example", "/fallback.svg", app_screen_items),
			"/example.svg",
		)

	def test_route_variants_ignore_query_and_trailing_slash(self):
		self.assertEqual(
			get_route_variants("/app/example/?view=list"),
			("/app/example", "/desk/example"),
		)
