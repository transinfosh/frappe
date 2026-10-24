import { readFileSync } from "node:fs";
import path from "node:path";
import { test, expect } from "@playwright/test";

const desk_source = readFileSync(
	path.resolve(__dirname, "../../frappe/public/js/frappe/desk.js"),
	"utf8"
);
// Load the real class without the document-ready application startup.
const application_source = desk_source.slice(desk_source.indexOf("frappe.Application = class"));

async function expect_favicon(page, route, href) {
	await page.evaluate((route) => {
		window.test_route = route;
		$(document).trigger("page-change");
	}, route);
	const icons = page.locator('link[rel~="icon"]');
	await expect(icons).toHaveCount(2);
	await expect(icons.nth(0)).toHaveAttribute("href", href);
	await expect(icons.nth(1)).toHaveAttribute("href", href);
}

test.beforeEach(async ({ page }) => {
	await page.setContent('<link rel="icon" type="image/x-icon" href="/default.ico">');
	await page.addScriptTag({ path: require.resolve("jquery/dist/jquery.js") });
	await page.evaluate(() => {
		window.test_route = [];
		window.locals = { Page: { "sales-page": { module: "Sales" } } };
		window.frappe = {
			get_route: () => window.test_route,
			get_meta: () => ({ module: "Sales" }),
			scrub: (value) => value.toLowerCase().replace(/ /g, "_"),
			router: { slug: (value) => value.toLowerCase().replace(/ /g, "-") },
			boot: {
				// Current boot payloads have dock entries, never app.workspaces.
				app_data: [
					{ app_name: "sales", app_logo_url: ["/old.svg", "/sales.svg"], dock: [] },
					{ app_name: "legacy", app_logo_url: "/legacy.svg", dock: [] },
					{ app_name: "no-brand", app_logo_url: [], dock: [] },
				],
				module_app: { sales: "sales", legacy_sales: "legacy" },
				module_sidebars: {
					"Sales Navigation": {
						name: "Sales Navigation",
						app: "sales",
						workspaces: ["Sales Home"],
					},
				},
			},
			workspaces: {
				"sales-home": { name: "Sales Home", module: "Legacy Sales", app: "legacy" },
				"my-sales": { name: "My Sales", module: "Sales", public: 0 },
				loose: { name: "Loose", app: "sales" },
				"no-brand": { name: "No Brand", app: "no-brand" },
				"unknown-app": { name: "Unknown App", app: "uninstalled" },
			},
		};
	});
	await page.addScriptTag({ content: application_source });
	await page.evaluate(() => {
		frappe.app = Object.create(frappe.Application.prototype);
		frappe.app.set_favicon();
	});
});

test("uses the workspace sidebar's app and the last logo hook", async ({ page }) => {
	await expect_favicon(page, ["Workspaces", "Sales Home"], "/sales.svg");
});

test("uses the host app for a companion workspace", async ({ page }) => {
	await page.evaluate(() => {
		frappe.boot.app_rail_host = { sales: "legacy" };
	});
	await expect_favicon(page, ["Workspaces", "Sales Home"], "/legacy.svg");
});

test("uses workspace app metadata when no sidebar owns it", async ({ page }) => {
	await expect_favicon(page, ["Workspaces", "Loose"], "/sales.svg");
});

test("keeps the module_app fallback for private workspaces", async ({ page }) => {
	await expect_favicon(page, ["Workspaces", "private", "My Sales"], "/sales.svg");
});

for (const route of [
	["Workspaces"],
	["Workspaces", "private"],
	["Workspaces", "Missing"],
	["Workspaces", "Unknown App"],
	["Workspaces", "No Brand"],
]) {
	test(`restores the default favicon for ${route.join("/")}`, async ({ page }) => {
		await expect_favicon(page, ["Form", "Order", "ORDER-1"], "/sales.svg");
		await expect_favicon(page, route, "/default.ico");
	});
}

test("tolerates missing workspace and boot lookup maps", async ({ page }) => {
	await page.evaluate(() => {
		delete frappe.workspaces;
		delete frappe.boot.module_sidebars;
		delete frappe.boot.module_app;
		delete frappe.boot.app_data;
	});
	await expect_favicon(page, ["Workspaces", "Missing"], "/default.ico");
});

for (const route of [
	["Form", "Order", "ORDER-1"],
	["List", "Order", "List"],
	["Tree", "Territory"],
	["sales-page"],
]) {
	test(`keeps module favicon resolution for ${route[0]}`, async ({ page }) => {
		await expect_favicon(page, route, "/sales.svg");
	});
}
