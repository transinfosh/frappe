# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE
import os

no_cache = 1

import json
import re
from typing import Any
from urllib.parse import urlencode

import frappe
import frappe.sessions
from frappe import _
from frappe.utils.jinja_globals import is_rtl

SCRIPT_TAG_PATTERN = re.compile(r"\<script[^<]*\</script\>")
CLOSING_SCRIPT_TAG_PATTERN = re.compile(r"</script\>")


def get_context(context):
	desk_favicon = frappe.get_hooks("desk_favicon")
	default_favicon = desk_favicon[-1] if desk_favicon else context.get("favicon")

	if frappe.session.user == "Guest":
		frappe.response["status_code"] = 403
		frappe.msgprint(_("Log in to access this page."))
		frappe.redirect(f"/login?{urlencode({'redirect-to': frappe.request.path})}")

	elif frappe.session.data.user_type == "Website User" and frappe.session.user != "Administrator":
		frappe.throw(_("You are not permitted to access this page."), frappe.PermissionError)

	try:
		boot = frappe.sessions.get()
	except Exception as e:
		raise frappe.SessionBootFailed from e

	# this needs commit
	csrf_token = frappe.sessions.get_csrf_token()

	hooks = frappe.get_hooks()
	app_include_js = hooks.get("app_include_js", []) + frappe.conf.get("app_include_js", [])
	app_include_css = hooks.get("app_include_css", []) + frappe.conf.get("app_include_css", [])
	app_include_icons = hooks.get("app_include_icons", [])

	if frappe.get_system_settings("enable_telemetry") and os.getenv("FRAPPE_SENTRY_DSN"):
		app_include_js.append("sentry.bundle.js")

	context.update(
		{
			"no_cache": 1,
			"build_version": frappe.utils.get_build_version(),
			"app_include_js": app_include_js,
			"app_include_css": app_include_css,
			"app_include_icons": app_include_icons,
			"layout_direction": "rtl" if is_rtl() else "ltr",
			"lang": frappe.local.lang,
			"sounds": hooks["sounds"],
			"boot": boot,
			"desk_theme": boot.get("desk_theme") or "Light",
			"csrf_token": csrf_token,
			"google_analytics_id": frappe.conf.get("google_analytics_id"),
			"google_analytics_anonymize_ip": frappe.conf.get("google_analytics_anonymize_ip"),
			"favicon": default_favicon,
			"splash_image": get_app_splash_image(
				boot,
				frappe.request.path,
				context.get("splash_image") or default_favicon,
				hooks.get("add_to_apps_screen", []),
			),
			"app_name": (
				frappe.get_website_settings("app_name") or frappe.get_system_settings("app_name") or "Frappe"
			),
		}
	)

	return context


def get_app_splash_image(
	boot: dict[str, Any],
	request_path: str,
	fallback: str | None,
	app_screen_items: list[dict[str, Any]] | None = None,
) -> str | None:
	request_path = f"/{request_path.strip('/')}"
	matched_app = None
	matched_route_length = 0
	app_screen_routes = {
		item.get("name"): item.get("route")
		for item in app_screen_items or []
		if item.get("name") and item.get("route")
	}

	for app in boot.get("app_data", []):
		routes = (app.get("app_route"), app_screen_routes.get(app.get("app_name")))
		for route in routes:
			for app_route in get_route_variants(route):
				if request_path == app_route or request_path.startswith(f"{app_route}/"):
					if len(app_route) > matched_route_length:
						matched_app = app
						matched_route_length = len(app_route)

	if not matched_app:
		return fallback

	app_logo = matched_app.get("app_logo_url")
	if isinstance(app_logo, (list, tuple)):
		app_logo = app_logo[-1] if app_logo else None

	return app_logo or fallback


def get_route_variants(route: str | None) -> tuple[str, ...]:
	route = (route or "").split("?", 1)[0].rstrip("/")
	if not route:
		return ()

	variants = [route]
	if route.startswith("/app/"):
		variants.append(f"/desk/{route.removeprefix('/app/')}")
	elif route.startswith("/desk/"):
		variants.append(f"/app/{route.removeprefix('/desk/')}")

	return tuple(variants)
