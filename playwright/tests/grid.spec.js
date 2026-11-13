import { test, expect } from "../support";

test.describe("Grid", () => {
	test.beforeAll(async ({ admin }) => {
		await admin.call("frappe.tests.ui_test_helpers.create_contact_phone_nos_records");
	});

	test.beforeEach(async ({ page }) => {
		await page.goto("/desk/contact/Test Contact");
		await page.waitForFunction(
			() =>
				window.cur_frm &&
				cur_frm.doc.name === "Test Contact" &&
				cur_frm.get_field("phone_nos")
		);
	});

	const get_table = (page, fieldname = "phone_nos") =>
		page.locator(`.frappe-control[data-fieldname="${fieldname}"]`);

	const enable_bulk_edit = (page, enabled = true) =>
		page.evaluate((enabled) => {
			const grid = cur_frm.get_field("phone_nos").grid;
			grid.meta.allow_bulk_edit = enabled;
			grid.refresh_edit_rows_button();
		}, enabled);

	test("keeps retained child rows registered when server snapshots change the table", async ({
		page,
	}) => {
		const snapshots = await page.evaluate(() => {
			const original = JSON.parse(JSON.stringify(cur_frm.doc));
			const rows = original.phone_nos.slice(0, 3);
			const grid = cur_frm.get_field("phone_nos").grid;
			const sync_rows = (incoming) => {
				const previous = new Map(cur_frm.doc.phone_nos.map((row) => [row.name, row]));
				const incoming_names = new Set(incoming.map((row) => row.name));
				frappe.model.sync({
					...original,
					phone_nos: incoming.map((row, index) => ({ ...row, idx: index + 1 })),
				});
				cur_frm.refresh_fields();
				grid.refresh();
				grid.refresh();
				return {
					expected: incoming.map((row) => row.name),
					replaced: cur_frm.doc.phone_nos
						.filter((row) => previous.has(row.name) && previous.get(row.name) !== row)
						.map((row) => row.name),
					uncleared: [...previous]
						.filter(
							([name, row]) =>
								!incoming_names.has(name) && locals[row.doctype]?.[name]
						)
						.map(([name]) => name),
					missing: cur_frm.doc.phone_nos
						.filter((row) => locals[row.doctype]?.[row.name] !== row)
						.map((row) => row.name),
					rendered: grid.grid_rows.map((row) => row.doc?.name),
					dom_count: grid.wrapper.find(".grid-body .rows > .grid-row").length,
				};
			};
			sync_rows(rows);
			const removed = sync_rows(rows.slice(1));
			const added = { ...rows[0], name: "new-server-snapshot-row", phone: "987654321" };
			const inserted = sync_rows([added, ...rows.slice(1)]);
			const reordered = sync_rows([rows[2], added, rows[1]]);
			const previous_row = locals[added.doctype][added.name];
			const overrides = frappe.meta.get_docfield_copy(added.doctype, added.name);
			overrides.phone.read_only = 1;
			const saved = { ...added, name: "saved-server-snapshot-row" };
			const renamed = sync_rows([rows[2], saved, rows[1]]);
			const rename_preserved = {
				row: locals[saved.doctype][saved.name] === previous_row,
				overrides: frappe.meta.docfield_copy[saved.doctype][saved.name] === overrides,
				old_override_removed: !frappe.meta.docfield_copy[added.doctype][added.name],
			};
			const cleared = sync_rows([]);
			return { changes: [removed, inserted, reordered, renamed, cleared], rename_preserved };
		});
		for (const snapshot of snapshots.changes) {
			expect(snapshot.replaced).toEqual([]);
			expect(snapshot.uncleared).toEqual([]);
			expect(snapshot.missing).toEqual([]);
			expect(snapshot.rendered).toEqual(snapshot.expected);
			expect(snapshot.dom_count).toBe(snapshot.expected.length);
		}
		expect(snapshots.rename_preserved).toEqual({
			row: true,
			overrides: true,
			old_override_removed: true,
		});
	});

	test("keeps close and navigation available on read-only row forms", async ({ page }) => {
		const table = get_table(page);
		const row_form = page.locator(".grid-row-open");
		await page.evaluate(() => cur_frm.set_df_property("phone_nos", "read_only", 1));
		await table.locator('[data-idx="1"] .btn-open-row').click();
		for (const selector of [
			".grid-collapse-row",
			".grid-first-row",
			".grid-prev-row",
			".grid-next-row",
			".grid-last-row",
		]) {
			await expect(row_form.locator(selector)).toBeVisible();
		}
		for (const selector of [
			".grid-move-row",
			".grid-duplicate-row",
			".grid-insert-row",
			".grid-insert-row-below",
			".grid-delete-row",
		]) {
			await expect(row_form.locator(selector)).toBeHidden();
		}
		await row_form.locator(".grid-next-row").click();
		await expect(row_form.locator(".grid-form-row-index")).toHaveText("2");
		await row_form.locator(".grid-prev-row").click();
		await expect(row_form.locator(".grid-form-row-index")).toHaveText("1");
		const row_count = await page.evaluate(
			() => cur_frm.get_field("phone_nos").grid.grid_rows.length
		);
		await row_form.locator(".grid-last-row").click();
		await expect(row_form.locator(".grid-form-row-index")).toHaveText(String(row_count));
		await row_form.locator(".grid-first-row").click();
		await expect(row_form.locator(".grid-form-row-index")).toHaveText("1");
		await row_form.locator(".grid-collapse-row").click();
		await expect(row_form).toHaveCount(0);
		await expect.poll(() => page.evaluate(() => cur_frm.is_dirty())).toBeFalsy();
		await page.evaluate(() => cur_frm.set_df_property("phone_nos", "read_only", 0));
		await table.locator('[data-idx="1"] .btn-open-row').click();
		await expect(row_form.locator(".grid-insert-row")).toBeVisible();
		await expect(row_form.locator(".grid-delete-row")).toBeVisible();
	});

	test("update docfield property using update_docfield_property", async ({ page }) => {
		const table = get_table(page);
		const table_form = page.locator(".grid-row-open");
		await page.evaluate(() =>
			cur_frm
				.get_field("phone_nos")
				.grid.update_docfield_property("is_primary_phone", "hidden", true)
		);

		for (const idx of [1, 2]) {
			await table.locator(`[data-idx="${idx}"] .btn-open-row`).click();
			await expect(
				table_form.locator('.frappe-control[data-fieldname="is_primary_phone"]')
			).toBeHidden();
			await table_form.locator(".grid-collapse-row").click();
		}
	});

	test("update docfield property using toggle_display", async ({ page }) => {
		const table = get_table(page);
		const table_form = page.locator(".grid-row-open");
		await page.evaluate(() =>
			cur_frm.get_field("phone_nos").grid.toggle_display("is_primary_mobile_no", false)
		);

		for (const idx of [1, 2]) {
			await table.locator(`[data-idx="${idx}"] .btn-open-row`).click();
			await expect(
				table_form.locator('.frappe-control[data-fieldname="is_primary_mobile_no"]')
			).toBeHidden();
			await table_form.locator(".grid-collapse-row").click();
		}
	});

	test("update docfield property using toggle_enable", async ({ page }) => {
		const table = get_table(page);
		const table_form = page.locator(".grid-row-open");
		await page.evaluate(() =>
			cur_frm.get_field("phone_nos").grid.toggle_enable("phone", false)
		);

		for (const idx of [1, 2]) {
			await table.locator(`[data-idx="${idx}"] .btn-open-row`).click();
			await expect(
				table_form.locator('.frappe-control[data-fieldname="phone"] .control-value')
			).toHaveClass(/(^|\s)like-disabled-input(\s|$)/);
			await table_form.locator(".grid-collapse-row").click();
		}
	});

	test("update docfield property using toggle_reqd", async ({ page, desk }) => {
		const table = get_table(page);
		const table_form = page.locator(".grid-row-open");
		await page.evaluate(() => cur_frm.get_field("phone_nos").grid.toggle_reqd("phone", false));

		for (const idx of [1, 2]) {
			await table.locator(`[data-idx="${idx}"] .btn-open-row`).click();
			await expect(table_form).toBeVisible();
			const phone_field = desk.get_field("phone");
			await phone_field.focus();
			await phone_field.clear();
			await phone_field.blur();
			await expect
				.poll(() =>
					page.evaluate((idx) => cur_frm.doc.phone_nos[idx - 1].phone || "", idx)
				)
				.toBe("");
			await expect(phone_field).not.toHaveClass(/(^|\s)has-error(\s|$)/);
			await table_form.locator(".grid-collapse-row").click();
		}
	});

	test("shows edit button only when child table allow_bulk_edit is enabled", async ({
		page,
	}) => {
		const table = get_table(page);

		await enable_bulk_edit(page, false);

		await table.locator('.grid-row[data-idx="1"] .grid-row-check').click();
		await expect(table.locator(".grid-edit-rows")).toHaveClass(/(^|\s)hidden(\s|$)/);

		await enable_bulk_edit(page, true);

		await expect(table.locator(".grid-edit-rows")).not.toHaveClass(/(^|\s)hidden(\s|$)/);
	});

	test("bulk edit updates only selected child rows", async ({ page }) => {
		const updated_phone = `99999${Date.now().toString().slice(-5)}`;
		const table = get_table(page);

		await enable_bulk_edit(page);
		const { row_count, phone_field_label, second_row_phone_before } = await page.evaluate(
			() => {
				const grid = cur_frm.get_field("phone_nos").grid;
				const phone_df = grid.docfields.find((df) => df.fieldname === "phone");
				return {
					row_count: cur_frm.doc.phone_nos.length,
					phone_field_label: phone_df && phone_df.label,
					second_row_phone_before: cur_frm.doc.phone_nos[1].phone || "",
				};
			}
		);
		expect(row_count).toBeGreaterThan(1);
		expect(phone_field_label).toBeTruthy();

		await table.locator('.grid-row[data-idx="1"] .grid-row-check').click();
		await table.locator(".grid-edit-rows").click();
		await page.waitForFunction(() => window.cur_dialog);

		await page.evaluate(
			async ([phone_field_label, updated_phone]) => {
				await cur_dialog.set_value("field", phone_field_label);
				await cur_dialog.set_value("value", updated_phone);
				cur_dialog.get_primary_btn().click();
			},
			[phone_field_label, updated_phone]
		);

		await expect
			.poll(() => page.evaluate(() => cur_frm.doc.phone_nos[0].phone))
			.toBe(updated_phone);
		expect(await page.evaluate(() => cur_frm.doc.phone_nos[1].phone || "")).toBe(
			second_row_phone_before
		);
	});

	test("shows bulk edit fields on submitted documents for allow-on-submit columns", async ({
		page,
	}) => {
		const table = get_table(page);

		await page.evaluate(() => {
			const grid = cur_frm.get_field("phone_nos").grid;
			grid.meta.allow_bulk_edit = true;
			grid.refresh_edit_rows_button();

			const phone_df = grid.docfields.find((df) => df.fieldname === "phone");
			phone_df.allow_on_submit = 1;
			cur_frm.doc.docstatus = 1;
		});

		await table.locator('.grid-row[data-idx="1"] .grid-row-check').click();
		await table.locator(".grid-edit-rows").click();

		const dialog = page.locator(".modal-dialog:visible");
		await expect(dialog.locator('.frappe-control[data-fieldname="field"]')).toBeVisible();
		await expect(dialog.locator('.frappe-control[data-fieldname="value"]')).toBeVisible();
	});

	test("hides add-row and add-multiple-rows buttons when rows are selected", async ({
		page,
	}) => {
		const table = get_table(page);
		const row_check = table.locator('.grid-row[data-idx="1"] .grid-row-check');

		await row_check.click();

		await expect(table.locator(".grid-add-row")).toHaveClass(/(^|\s)hidden(\s|$)/);
		await expect(table.locator(".grid-add-multiple-rows")).toHaveClass(/(^|\s)hidden(\s|$)/);

		await row_check.click();

		await expect(table.locator(".grid-add-row")).not.toHaveClass(/(^|\s)hidden(\s|$)/);
	});
});
