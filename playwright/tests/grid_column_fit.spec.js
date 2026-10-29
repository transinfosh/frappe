import { test, expect } from "../support";

const suffix = String(process.pid);
const parent_doctype = `Test Grid Fit ${suffix}`;
const child_doctype = `Test Grid Fit Row ${suffix}`;
const route = parent_doctype.toLowerCase().replace(/ /g, "-");
const long_value = `Second page ${"W".repeat(90)}`;
const defaults = [
	{ fieldname: "code", width: 90, sticky: 0 },
	{ fieldname: "description", width: 140, sticky: 0 },
	{ fieldname: "amount", width: 120, sticky: 0 },
	{ fieldname: "tail", width: 90, sticky: 0 },
];
const custom_columns = [
	{ fieldname: "description", width: 100, sticky: 0 },
	{ fieldname: "amount", width: 60, sticky: 0 },
	{ fieldname: "code", width: 100, sticky: 1 },
	{ fieldname: "extra", width: 110, sticky: 0 },
	{ fieldname: "tail", width: 90, sticky: 0 },
];

const table = (page) => page.locator('.frappe-control[data-fieldname="items"]');
const dialog = (page) => page.locator(".modal.show", { hasText: "Configure Columns" });

async function open_configuration(page) {
	await table(page).locator(".grid-heading-row .grid-static-col.pointer").click();
	await expect(dialog(page)).toBeVisible();
	return dialog(page);
}

async function configured_columns(page) {
	return page.evaluate(
		() =>
			window.cur_frm?.fields_dict?.items?.grid?.visible_columns?.map(([df, width]) => ({
				fieldname: df.fieldname,
				width,
				sticky: Number(df.sticky || 0),
			})) || []
	);
}

async function draft_columns(page) {
	return dialog(page)
		.locator(".fields_order")
		.evaluateAll((rows) =>
			rows.map((row) => ({
				fieldname: row.dataset.fieldname,
				width: Number(row.querySelector(".column-width").value),
				sticky: Number(row.querySelector(".sticky-column").checked),
			}))
		);
}

async function server_settings(api) {
	const response = await api.call("frappe.model.utils.user_settings.get", {
		doctype: parent_doctype,
	});
	return JSON.parse(response.message || "{}");
}

test.describe("Grid content fitting", () => {
	let document_name;
	let empty_document_name;
	let created_parent = false;
	let created_child = false;

	test.beforeAll(async ({ admin }) => {
		expect(process.env.BASE_URL, "Use an explicit disposable test site BASE_URL").toBeTruthy();
		expect(new URL(process.env.BASE_URL).hostname).not.toBe("development.localhost");
		await admin.insert_doc("DocType", {
			name: child_doctype,
			title: "列宽测试明细",
			module: "Core",
			custom: 1,
			istable: 1,
			editable_grid: 1,
			fields: [
				{
					fieldname: "code",
					label: "Code",
					fieldtype: "Data",
					in_list_view: 1,
					width: "90",
				},
				{
					fieldname: "description",
					label: "Description",
					fieldtype: "Data",
					in_list_view: 1,
					width: "140",
				},
				{
					fieldname: "amount",
					label: "Value",
					fieldtype: "Float",
					precision: "2",
					in_list_view: 1,
					width: "120",
				},
				{
					fieldname: "tail",
					label: "Note",
					fieldtype: "Data",
					in_list_view: 1,
					width: "90",
				},
				{ fieldname: "extra", label: "Extra", fieldtype: "Data", width: "200" },
				{ fieldname: "secret", label: "Password", fieldtype: "Password", width: "100" },
				{
					fieldname: "conditional",
					label: "Conditional",
					fieldtype: "Data",
					depends_on: 'eval:doc.code === "SHOW"',
				},
			],
		});
		created_child = true;
		await admin.insert_doc("DocType", {
			name: parent_doctype,
			title: "列宽测试",
			module: "Core",
			custom: 1,
			fields: [
				{ fieldname: "items", label: "Items", fieldtype: "Table", options: child_doctype },
			],
			permissions: [{ role: "System Manager", read: 1, write: 1, create: 1, delete: 1 }],
		});
		created_parent = true;
		const document = await admin.insert_doc(parent_doctype, {
			items: Array.from({ length: 55 }, (_, index) => ({
				code: `R${index + 1}`,
				description: index === 50 ? long_value : "Short",
				amount: index === 50 ? 1234567890.25 : 1.25,
				tail: "End",
				extra: "Optional",
			})),
		});
		document_name = document.name;
		empty_document_name = (await admin.insert_doc(parent_doctype, {})).name;
	});

	test.afterAll(async ({ admin }) => {
		if (document_name) await admin.remove_doc(parent_doctype, document_name, true);
		if (empty_document_name) await admin.remove_doc(parent_doctype, empty_document_name, true);
		if (created_parent) await admin.remove_doc("DocType", parent_doctype, true);
		if (created_child) await admin.remove_doc("DocType", child_doctype, true);
	});

	test.beforeEach(async ({ api, page }) => {
		await api.call("frappe.model.utils.user_settings.save", {
			doctype: parent_doctype,
			user_settings: JSON.stringify({ GridView: { [child_doctype]: custom_columns } }),
		});
		await page.goto(`/desk/${route}/${document_name}`);
		await expect(table(page).locator(".grid-body .rows .grid-row")).toHaveCount(50);
	});

	test.afterEach(async ({ api }) => {
		await api.call("frappe.model.utils.user_settings.save", {
			doctype: parent_doctype,
			user_settings: JSON.stringify({ GridView: null }),
		});
	});

	test("fit includes off-page formatted values but cancelling leaves document and preferences untouched", async ({
		page,
		api,
	}) => {
		const saved = await server_settings(api);
		const original = await configured_columns(page);
		expect(original).toEqual(custom_columns);
		await expect(table(page).getByText(long_value, { exact: true })).toHaveCount(0);
		const writes = [];
		page.on("request", (request) => {
			if (request.url().includes("frappe.model.utils.user_settings.save"))
				writes.push(request);
		});
		const modal = await open_configuration(page);
		await modal.getByRole("button", { name: "Fit Columns To Content", exact: true }).click();
		const fitted = await draft_columns(page);
		expect(fitted.map(({ fieldname, sticky }) => ({ fieldname, sticky }))).toEqual(
			custom_columns.map(({ fieldname, sticky }) => ({ fieldname, sticky }))
		);
		expect(fitted.find((column) => column.fieldname === "description").width).toBe(600);
		expect(fitted.find((column) => column.fieldname === "amount").width).toBeGreaterThan(100);
		expect(fitted.every(({ width }) => width >= 60 && width <= 600)).toBe(true);
		expect(await configured_columns(page)).toEqual(original);
		await modal.locator(".btn-modal-close").click();
		await expect(modal).toBeHidden();
		expect(await server_settings(api)).toEqual(saved);
		expect(await configured_columns(page)).toEqual(original);
		expect(await page.evaluate(() => cur_frm.is_dirty())).toBeFalsy();
		expect(writes).toHaveLength(0);
		await open_configuration(page);
		expect(await draft_columns(page)).toEqual(original);
	});

	test("Update persists once per user and Reset immediately restores default columns, widths and sticky state", async ({
		page,
		api,
		admin,
	}) => {
		const modal = await open_configuration(page);
		const writes = [];
		page.on("request", (request) => {
			if (request.url().includes("frappe.model.utils.user_settings.save"))
				writes.push(request);
		});
		await modal.getByRole("button", { name: "Fit Columns To Content", exact: true }).click();
		const fitted = await draft_columns(page);
		await modal.getByRole("button", { name: "Update", exact: true }).click();
		await expect.poll(() => configured_columns(page)).toEqual(fitted);
		await expect
			.poll(async () => (await server_settings(api)).GridView?.[child_doctype])
			.toEqual(fitted);
		expect(writes).toHaveLength(1);
		expect(await page.evaluate(() => cur_frm.is_dirty())).toBeFalsy();
		expect((await server_settings(admin)).GridView?.[child_doctype]).toBeUndefined();
		await page.reload();
		await expect.poll(() => configured_columns(page)).toEqual(fitted);
		await table(page).locator(".next-page").click();
		const amount = table(page).locator(
			'.grid-row[data-idx="51"] [data-fieldname="amount"] .static-area'
		);
		await expect(amount).toContainText("1,234,567,890.25");
		const numeric_width = await amount.evaluate((element) => {
			const range = document.createRange();
			range.selectNodeContents(element);
			return range.getBoundingClientRect().width;
		});
		expect(numeric_width).toBeLessThanOrEqual(
			fitted.find((column) => column.fieldname === "amount").width
		);
		await open_configuration(page);
		await modal.getByRole("button", { name: "Reset to default", exact: true }).click();
		await expect.poll(() => configured_columns(page)).toEqual(defaults);
		await expect(table(page).locator(".sticky-grid-col[data-fieldname]")).toHaveCount(0);
		expect((await server_settings(api)).GridView).toBeNull();
		expect(await page.evaluate(() => cur_frm.is_dirty())).toBeFalsy();
		await open_configuration(page);
		expect(await draft_columns(page)).toEqual(defaults);
		await modal.locator(".btn-modal-close").click();
		await page.reload();
		await expect.poll(() => configured_columns(page)).toEqual(defaults);
	});

	test("empty grids fit headers and remain usable without creating document changes", async ({
		page,
		api,
	}) => {
		await page.goto(`/desk/${route}/${empty_document_name}`);
		const modal = await open_configuration(page);
		await modal.getByRole("button", { name: "Fit Columns To Content", exact: true }).click();
		const fitted = await draft_columns(page);
		expect(fitted).toHaveLength(custom_columns.length);
		expect(fitted.every(({ width }) => width >= 60 && width <= 600)).toBe(true);
		expect(fitted.find((column) => column.fieldname === "description").width).toBeLessThan(
			200
		);
		await modal.getByRole("button", { name: "Update", exact: true }).click();
		await expect.poll(() => configured_columns(page)).toEqual(fitted);
		expect((await server_settings(api)).GridView[child_doctype]).toEqual(fitted);
		expect(await page.evaluate(() => cur_frm.is_dirty())).toBeFalsy();
		await expect(table(page).locator(".grid-body .rows .grid-row")).toHaveCount(0);
	});

	test("real column dragging still persists and Reset restores defaults with and without saved preferences", async ({
		page,
		api,
	}) => {
		for (const saved_columns of [null, custom_columns]) {
			await api.call("frappe.model.utils.user_settings.save", {
				doctype: parent_doctype,
				user_settings: JSON.stringify({
					GridView: saved_columns && { [child_doctype]: saved_columns },
				}),
			});
			await page.reload();
			await expect.poll(() => configured_columns(page)).toEqual(saved_columns || defaults);
			const handle = table(page).locator(
				'.grid-heading-row [data-fieldname="code"] .grid-col-resize-handle'
			);
			await handle.scrollIntoViewIfNeeded();
			const original_width = await handle.evaluate(
				(element) => element.closest(".grid-static-col").getBoundingClientRect().width
			);
			const bounds = await handle.boundingBox();
			await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
			await page.mouse.down();
			await page.mouse.move(bounds.x + bounds.width / 2 + 75, bounds.y + bounds.height / 2, {
				steps: 8,
			});
			await page.mouse.up();
			await expect
				.poll(async () => {
					const saved = (await server_settings(api)).GridView?.[child_doctype]?.find(
						(column) => column.fieldname === "code"
					)?.width;
					return Math.abs(saved - original_width - 75);
				})
				.toBeLessThan(1);
			await page.evaluate(() => {
				cur_frm.fields_dict.items.grid.update_docfield_property(
					"code",
					"label",
					"Updated Code"
				);
			});
			await expect(
				table(page)
					.locator('.grid-heading-row .grid-static-col[data-fieldname="code"]')
					.first()
			).toContainText("Updated Code");
			const modal = await open_configuration(page);
			expect(
				Math.abs(
					(await draft_columns(page)).find((column) => column.fieldname === "code")
						.width -
						original_width -
						75
				)
			).toBeLessThan(1);
			await modal.getByRole("button", { name: "Reset to default", exact: true }).click();
			await expect.poll(() => configured_columns(page)).toEqual(defaults);
			await expect(table(page).locator(".sticky-grid-col[data-fieldname]")).toHaveCount(0);
			expect((await server_settings(api)).GridView).toBeNull();
			expect(await page.evaluate(() => cur_frm.is_dirty())).toBeFalsy();
		}
	});

	test("Chinese text is bounded while passwords and conditionally hidden values reveal no length", async ({
		page,
		api,
	}) => {
		const columns = ["description", "secret", "conditional", "tail"].map((fieldname) => ({
			fieldname,
			width: 100,
			sticky: 0,
		}));
		await api.call("frappe.model.utils.user_settings.save", {
			doctype: parent_doctype,
			user_settings: JSON.stringify({ GridView: { [child_doctype]: columns } }),
		});
		await page.reload();
		await expect.poll(() => configured_columns(page)).toEqual(columns);
		await page.evaluate(() => {
			for (const row of cur_frm.doc.items) {
				row.description = "中文内容";
				row.secret = "x";
				row.conditional = "";
			}
			cur_frm.refresh_field("items");
		});
		let modal = await open_configuration(page);
		await modal.getByRole("button", { name: "Fit Columns To Content", exact: true }).click();
		const short = await draft_columns(page);
		await modal.locator(".btn-modal-close").click();
		await expect(modal).toBeHidden();
		await page.evaluate(() => {
			for (const row of cur_frm.doc.items) {
				row.secret = "x".repeat(200);
				row.conditional = "W".repeat(200);
			}
			cur_frm.doc.items[50].description = "中文内容自适应列宽".repeat(40);
			cur_frm.refresh_field("items");
		});
		modal = await open_configuration(page);
		await modal.getByRole("button", { name: "Fit Columns To Content", exact: true }).click();
		const long = await draft_columns(page);
		expect(long.find((column) => column.fieldname === "description").width).toBe(600);
		for (const fieldname of ["secret", "conditional"]) {
			expect(long.find((column) => column.fieldname === fieldname).width).toBe(
				short.find((column) => column.fieldname === fieldname).width
			);
		}
	});

	test("off-page conditional mandatory text fits its bold rendered content", async ({
		page,
	}) => {
		await page.evaluate(() => {
			const grid = cur_frm.fields_dict.items.grid;
			grid.update_docfield_property(
				"description",
				"mandatory_depends_on",
				'eval:doc.code === "R51"'
			);
			for (const row of cur_frm.doc.items) row.description = "Short";
			cur_frm.doc.items[50].description = "W".repeat(20);
			cur_frm.refresh_field("items");
		});
		await expect(
			table(page).locator('.grid-row[data-idx="1"] [data-fieldname="description"]')
		).not.toHaveClass(/bold/);
		const modal = await open_configuration(page);
		await modal.getByRole("button", { name: "Fit Columns To Content", exact: true }).click();
		const fitted = await draft_columns(page);
		await modal.getByRole("button", { name: "Update", exact: true }).click();
		await expect.poll(() => configured_columns(page)).toEqual(fitted);
		await table(page).locator(".next-page").click();
		const cell = table(page).locator(
			'.grid-row[data-idx="51"] [data-fieldname="description"]'
		);
		await expect(cell).toHaveClass(/bold/);
		const content_width = await cell.evaluate((element) => {
			const range = document.createRange();
			range.selectNodeContents(element.querySelector(".static-area"));
			const style = getComputedStyle(element);
			return (
				range.getBoundingClientRect().width +
				parseFloat(style.paddingLeft) +
				parseFloat(style.paddingRight)
			);
		});
		expect(content_width).toBeLessThanOrEqual(
			fitted.find((column) => column.fieldname === "description").width
		);
	});
});
