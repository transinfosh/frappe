import { readFileSync } from "node:fs";
import path from "node:path";
import { test, expect } from "@playwright/test";

// Exercise the real selection handlers without a site or database fixtures.
const list_view_source = readFileSync(
	path.resolve(__dirname, "../../frappe/public/js/frappe/list/list_view.js"),
	"utf8"
).replace(/^import .*;\n/gm, "");

for (const names of [
	[101, 102, 103],
	["DOC-101", "DOC-102", "DOC-103"],
]) {
	test.describe(`List selection with ${typeof names[0]} names`, () => {
		test.beforeEach(async ({ page }) => {
			await page.setContent('<div id="result"></div>');
			await page.addScriptTag({ path: require.resolve("jquery/dist/jquery.js") });
			await page.evaluate(() => {
				window.frappe = { provide() {}, views: { BaseList: class {} } };
				window.cstr = (value) => String(value);
			});
			await page.addScriptTag({ content: list_view_source });
			await page.evaluate((names) => {
				window.cur_list = Object.create(frappe.views.ListView.prototype);
				cur_list.data = names.map((name) => ({ name }));
				cur_list.checked_docnames = new Set();
				cur_list.$result = $("#result");
				cur_list.on_row_checked = () => {};
				cur_list.$result.append(
					'<div class="checkbox-actions"><input type="checkbox" class="list-check-all"></div>'
				);
				names.forEach((name) => {
					const $row = $('<div class="list-row-container"></div>');
					$('<input type="checkbox" class="list-row-checkbox">')
						.attr("data-name", name)
						.appendTo($row);
					cur_list.$result.append($row);
				});
				cur_list.setup_check_events();
			}, names);
		});

		test("excludes an unchecked row from bulk operations after select-all", async ({
			page,
		}) => {
			await page.locator(".list-check-all").check();
			await page.locator(".list-row-checkbox").first().uncheck();

			expect(await page.evaluate(() => cur_list.get_checked_items(true))).toEqual(
				names.slice(1).map(String)
			);
			expect(
				await page.evaluate(() => cur_list.get_checked_items().map((doc) => doc.name))
			).toEqual(names.slice(1));
		});

		test("keeps a selected row through pruning and checkbox restoration", async ({ page }) => {
			await page.locator(".list-row-checkbox").first().check();
			await page.evaluate(() => {
				cur_list.prune_checked_docnames();
				cur_list.$result.find(".list-row-checkbox").prop("checked", false);
				cur_list.set_rows_as_checked();
			});

			await expect(page.locator(".list-row-checkbox").first()).toBeChecked();
			expect(await page.evaluate(() => cur_list.get_checked_items(true))).toEqual([
				String(names[0]),
			]);
		});

		test("shift-selects intermediate rows and allows removing them", async ({ page }) => {
			await page.locator(".list-row-checkbox").first().click();
			await page
				.locator(".list-row-checkbox")
				.last()
				.click({ modifiers: ["Shift"] });
			await expect(page.locator(".list-row-checkbox:checked")).toHaveCount(3);
			expect(await page.evaluate(() => cur_list.get_checked_items(true).sort())).toEqual(
				names.map(String).sort()
			);

			await page.locator(".list-row-checkbox").nth(1).uncheck();
			expect(await page.evaluate(() => cur_list.get_checked_items(true).sort())).toEqual(
				[names[0], names[2]].map(String).sort()
			);
		});
	});
}
