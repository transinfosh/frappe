import { test, expect } from "../support";

async function row_numbers(page) {
	return page.evaluate(() => {
		const manager = cur_list.datatable.datamanager;
		const serial_index = manager.getColumnIndexById("_rowIndex");
		return manager.rows.map((row) => row[serial_index].content);
	});
}

// Uses existing framework metadata; never writes business records.
test("Report View detail groups preserve summaries, selection, modes and saved settings", async ({
	page,
	desk,
}) => {
	await page.goto("/desk/doctype/view/report");
	await desk.ready();
	await page.waitForFunction(() => cur_list.group_by_control && cur_list.datatable);
	await desk.clear_filters();
	await page.evaluate(async () => {
		await cur_list.filter_area.add("DocType", "name", "in", ["DocType", "DocField", "Report"]);
		cur_list.fields = [
			["name", "DocType"],
			["module", "DocType"],
		];
		cur_list.start = 0;
		cur_list.page_length = 1;
		await cur_list.refresh();
	});
	await page.locator(".group-by-button:visible").click();
	await page.waitForFunction(() => cur_list.group_by_control.group_mode_select?.length);
	await expect(page.locator(".group-by-popover p")).toHaveCount(0);
	await page.locator(".group-mode:visible").selectOption("detail");
	while ((await page.locator(".detail-group-remove:visible").count()) > 1) {
		await page.locator(".detail-group-remove:visible").last().click();
	}
	await page.locator("select.detail-group-field:visible").first().selectOption("module");
	await page.waitForFunction(
		() =>
			JSON.stringify(cur_list.detail_group_summary?.fieldnames) === '["module"]' &&
			cur_list.data.length === 1
	);
	await page.waitForFunction(() => cur_list.detail_group_summary?.groups?.[0]?._count === 3);
	await page.evaluate(() => cur_list.group_by_control.group_by_button.popover("hide"));
	await expect(page.locator(".report-group-heading")).toContainText("1 of 3 loaded");
	await expect(page.locator(".report-group-heading")).toContainText("Core");
	const merged = page.locator(".report-group-span-cell");
	expect(Number(await merged.getAttribute("aria-colspan"))).toBe(
		await page.evaluate(() => cur_list.columns.length + 1)
	);
	const merged_alignment = await page.evaluate(() => {
		const table = cur_list.datatable;
		const merged = table.bodyScrollable
			.querySelector(".report-group-span-cell")
			.getBoundingClientRect();
		const last = table.header
			.querySelector(".dt-row-header > .dt-cell:last-child")
			.getBoundingClientRect();
		return Math.abs(merged.right - last.right);
	});
	expect(merged_alignment).toBeLessThan(2);

	expect(
		await page.evaluate(
			() =>
				cur_list.datatable.datamanager
					.getColumns()
					.find((column) => column.field === "name").width
		)
	).toBeLessThan(430);

	expect(await row_numbers(page)).toEqual(["", 1]);

	await page.locator(".report-group-load").click();
	await page.waitForFunction(() => !cur_list.detail_group_loading?.size);
	await expect(page.locator(".report-group-heading")).toContainText("3 of 3 loaded");
	expect(await row_numbers(page)).toEqual(["", 1, 2, 3]);
	await page.evaluate(() => cur_list.datatable.rowmanager.checkAll(true));
	const selected = await page.evaluate(() => cur_list.get_checked_items(true));
	expect(selected.sort()).toEqual(["DocField", "DocType", "Report"]);

	await page.getByRole("button", { name: "Collapse All", exact: true }).click();
	expect(await row_numbers(page)).toEqual([""]);
	expect(await page.evaluate(() => cur_list.detail_row_documents.filter(Boolean))).toHaveLength(
		0
	);
	expect(await page.evaluate(() => cur_list.get_checked_items(true))).toHaveLength(0);
	await page.getByRole("button", { name: "Expand All", exact: true }).click();
	expect(await row_numbers(page)).toEqual(["", 1, 2, 3]);
	expect(await page.evaluate(() => cur_list.detail_row_documents.filter(Boolean))).toHaveLength(
		3
	);

	await page.locator(".group-by-button:visible").click();
	await page.locator(".group-mode:visible").selectOption("summary");
	await page.waitForFunction(() => cur_list.fields.some(([f]) => f === "_aggregate_column"));
	await page.waitForFunction(() => cur_list.data[0]?._aggregate_column === 3);
	await expect(page.locator(".report-detail-group-toolbar")).toBeHidden();
	expect(await row_numbers(page)).toEqual(["1"]);
	await expect(page.locator(".group-by-popover p")).toHaveCount(0);
	await page.locator(".group-mode:visible").selectOption("detail");
	await page.waitForFunction(() => cur_list.detail_group_summary?.groups?.[0]?._count === 3);
	expect(
		await page.evaluate(() => cur_list.fields.filter(([f]) => f === "module"))
	).toHaveLength(1);
	await page.evaluate(() => cur_list.group_by_control.group_by_button.popover("hide"));
	await page.waitForTimeout(500); // Wait for the standard debounced user-settings save.
	await page.reload();
	await desk.ready();
	await page.waitForFunction(
		() => cur_list.is_detail_grouped() && cur_list.detail_group_summary
	);
	await expect(page.locator(".report-group-heading")).toContainText("Core");

	// Reopening a legacy summary has no in-memory snapshot of the original columns.
	await page.locator(".group-by-button:visible").click();
	await page.waitForFunction(() => cur_list.group_by_control.group_mode_select?.length);
	await page.locator(".group-mode:visible").selectOption("summary");
	await page.waitForFunction(() => cur_list.data[0]?._aggregate_column === 3);
	await page.waitForTimeout(500);
	await page.reload();
	await desk.ready();
	await page.locator(".group-by-button:visible").click();
	await page.waitForFunction(() => cur_list.group_by_control.group_mode_select?.length);
	await page.locator(".group-mode:visible").selectOption("detail");
	await page.waitForFunction(() => cur_list.detail_group_summary?.groups?.[0]?._count === 3);
	expect(
		await page.evaluate(() => cur_list.fields.some(([f]) => f === "_aggregate_column"))
	).toBe(false);
});

test("Report View grouping levels can be added, reordered, removed and restored", async ({
	page,
	desk,
}) => {
	await page.goto("/desk/doctype/view/report");
	await desk.ready();
	await page.waitForFunction(() => cur_list.group_by_control && cur_list.datatable);
	await desk.clear_filters();
	await page.evaluate(async () => {
		await cur_list.filter_area.add("DocType", "name", "in", ["DocType", "DocField", "Report"]);
		cur_list.start = 0;
		cur_list.page_length = 1;
		await cur_list.refresh();
	});
	await page.locator(".group-by-button:visible").click();
	await page.waitForFunction(() => cur_list.group_by_control.group_mode_select?.length);
	await page.locator(".group-mode:visible").selectOption("detail");
	await page.locator(".detail-group-field:visible").first().selectOption("module");
	await page.locator(".add-detail-group-level").click();
	await page.locator(".detail-group-field:visible").nth(1).selectOption("istable");
	await page.waitForFunction(
		() => JSON.stringify(cur_list.detail_group_summary?.fieldnames) === '["module","istable"]'
	);
	await expect(
		page.locator(".detail-group-field:visible").nth(1).locator('option[value="module"]')
	).toBeDisabled();
	await page.evaluate(() => cur_list.group_by_control.group_by_button.popover("hide"));
	await expect(page.locator('.report-group-heading[data-level="0"]')).toHaveCount(1);
	await expect(page.locator('.report-group-heading[data-level="1"]')).toHaveCount(2);

	await page.locator('.report-group-heading[data-level="0"] .report-group-toggle').click();
	await expect(page.locator('.report-group-heading[data-level="1"]')).toHaveCount(0);
	expect(await page.evaluate(() => cur_list.detail_row_documents.filter(Boolean))).toHaveLength(
		0
	);
	await page.locator('.report-group-heading[data-level="0"] .report-group-toggle').click();
	await expect(page.locator('.report-group-heading[data-level="1"]')).toHaveCount(2);
	const request = page.waitForRequest(
		(r) => r.url().includes("frappe.desk.reportview.get") && !r.url().includes("get_count")
	);
	await page.locator(".report-group-load").first().click();
	const args = new URLSearchParams((await request).postData());
	const filters = JSON.parse(args.get("filters"));
	expect(filters).toContainEqual(["DocType", "module", "=", "Core"]);
	expect(filters).toContainEqual(["DocType", "istable", "=", 0]);
	await page.waitForFunction(() => !cur_list.detail_group_loading?.size);
	expect(
		await page.evaluate(() => cur_list.detail_row_documents.filter(Boolean).length)
	).toBeGreaterThanOrEqual(2);

	while (await page.locator(".report-group-load").count()) {
		await page.locator(".report-group-load").first().click();
		await page.waitForFunction(() => !cur_list.detail_group_loading?.size);
	}
	expect(await row_numbers(page)).toEqual(["", "", 1, 2, "", 1]);
	const serial_index = await page.evaluate(() =>
		cur_list.datatable.datamanager.getColumnIndexById("_rowIndex")
	);
	for (const cell of await page
		.locator(`.dt-row:has(.report-group-heading) .dt-cell--col-${serial_index}`)
		.all()) {
		await expect(cell).toHaveClass(/report-group-span-cell/);
	}
	await expect(page.locator(`.dt-cell--header-${serial_index} .dt-cell__content`)).toHaveText(
		"#"
	);
	await page
		.locator('.report-group-heading[data-level="1"] .report-group-toggle')
		.first()
		.click();
	expect(await row_numbers(page)).toEqual(["", "", "", 1]);
	await page
		.locator('.report-group-heading[data-level="1"] .report-group-toggle')
		.first()
		.click();
	expect(await row_numbers(page)).toEqual(["", "", 1, 2, "", 1]);

	// Delay an old leaf request while changing the field order.
	await page.evaluate(async () => {
		cur_list.start = 0;
		cur_list.last_args = null;
		await cur_list.refresh();
	});
	let release_leaf;
	const leaf_gate = new Promise((resolve) => {
		release_leaf = resolve;
	});
	await page.route("**/api/method/frappe.desk.reportview.get", async (route) => {
		const filters = JSON.parse(new URLSearchParams(route.request().postData()).get("filters"));
		if (filters.some((f) => f[1] === "module") && filters.some((f) => f[1] === "istable"))
			await leaf_gate;
		await route.continue();
	});
	const old_leaf_request = page.waitForRequest((r) =>
		r.url().endsWith("frappe.desk.reportview.get")
	);
	await page.locator(".report-group-load").first().click();
	await old_leaf_request;
	await page.locator(".group-by-button:visible").click();
	await page.locator(".detail-group-up").nth(1).click();
	await page.waitForFunction(
		() => JSON.stringify(cur_list.detail_group_summary?.fieldnames) === '["istable","module"]'
	);
	await page.evaluate(() => cur_list.group_by_control.group_by_button.popover("hide"));
	release_leaf();
	await page.waitForFunction(() => !cur_list.detail_group_loading?.size);
	expect(await page.evaluate(() => cur_list.detail_group_records.size)).toBe(0);
	await page.unroute("**/api/method/frappe.desk.reportview.get");
	await expect(page.locator('.report-group-heading[data-level="0"]')).toHaveCount(2);
	await expect(page.locator('.report-group-heading[data-level="1"]')).toHaveCount(2);
	await page
		.locator('.report-group-heading[data-level="0"] .report-group-toggle')
		.first()
		.click();
	await expect(page.locator('.report-group-heading[data-level="1"]')).toHaveCount(1);
	await page.getByRole("button", { name: "Expand All", exact: true }).click();
	await expect(page.locator('.report-group-heading[data-level="1"]')).toHaveCount(2);
	expect(
		await page.evaluate(() => JSON.parse(cur_list.get_search_params().get("_group_by"))[4])
	).toEqual(["`tabDocType`.`istable`", "`tabDocType`.`module`"]);
	await page.waitForTimeout(500);
	await page.reload();
	await desk.ready();
	await page.waitForFunction(
		() => JSON.stringify(cur_list.detail_group_summary?.fieldnames) === '["istable","module"]'
	);
	await page.locator(".group-by-button:visible").click();
	await page.waitForFunction(() => cur_list.group_by_control.group_mode_select?.length);
	await expect(page.locator(".detail-group-field").nth(0)).toHaveValue("istable");
	await expect(page.locator(".detail-group-field").nth(1)).toHaveValue("module");
	await page.locator(".add-detail-group-level").click();
	await page.locator(".detail-group-field").nth(2).selectOption("issingle");
	await page.waitForFunction(() => cur_list.detail_group_summary?.fieldnames?.length === 3);
	await page.locator(".detail-group-remove").nth(1).click();
	await page.waitForFunction(
		() =>
			JSON.stringify(cur_list.detail_group_summary?.fieldnames) === '["istable","issingle"]'
	);
});

test("Report group headings span text columns while totals remain aligned through resizing and scrolling", async ({
	page,
	desk,
}) => {
	await page.goto("/desk/doctype/view/report");
	await desk.ready();
	await page.waitForFunction(() => cur_list.group_by_control && cur_list.datatable);
	await desk.clear_filters();
	await page.evaluate(async () => {
		await cur_list.filter_area.add("DocType", "name", "in", ["DocType", "DocField", "Report"]);
		cur_list.fields = ["name", "module", "max_attachments", "issingle"].map((field) => [
			field,
			"DocType",
		]);
		cur_list.start = 0;
		cur_list.last_args = null;
		await cur_list.refresh();
	});
	await page.locator(".group-by-button:visible").click();
	await page.waitForFunction(() => cur_list.group_by_control.group_mode_select?.length);
	await page.locator(".group-mode:visible").selectOption("detail");
	while ((await page.locator(".detail-group-remove:visible").count()) > 1) {
		await page.locator(".detail-group-remove:visible").last().click();
	}
	await page.locator(".detail-group-field:visible").first().selectOption("module");
	await page.waitForFunction(
		() =>
			JSON.stringify(cur_list.detail_group_summary?.fieldnames) === '["module"]' &&
			cur_list.detail_group_summary?.sum_fields.includes("max_attachments")
	);
	await page.evaluate(() => cur_list.group_by_control.group_by_button.popover("hide"));
	const group = page.locator(".dt-row:has(.report-group-heading)");
	await expect(group.locator(".report-group-span-cell")).toHaveAttribute("aria-colspan", "3");

	const geometry = () =>
		page.evaluate(() => {
			const table = cur_list.datatable;
			const columns = table.datamanager.getColumns();
			const total_index = columns.find((col) => col.field === "max_attachments").colIndex;
			const name_column = columns.find((col) => col.field === "name");
			const group = table.bodyScrollable.querySelector(".dt-row:has(.report-group-heading)");
			const title = group.querySelector(".report-group-span-cell").getBoundingClientRect();
			const total = group
				.querySelector(`.dt-cell--col-${total_index}`)
				.getBoundingClientRect();
			const detail_index = cur_list.detail_row_documents.findIndex(Boolean);
			const detail = table.bodyScrollable
				.querySelector(`.dt-row-${detail_index} .dt-cell--col-${total_index}`)
				.getBoundingClientRect();
			const header = table.header
				.querySelector(`.dt-cell--col-${total_index}`)
				.getBoundingClientRect();
			return {
				title_end: title.right,
				total_start: total.left,
				detail_start: detail.left,
				header_start: header.left,
				name_width: name_column.width,
				name_index: name_column.colIndex,
			};
		});
	const serial_start = await page.evaluate(() => {
		const table = cur_list.datatable;
		const index = table.datamanager.getColumnIndexById("_rowIndex");
		return Math.abs(
			table.header.querySelector(`.dt-cell--col-${index}`).getBoundingClientRect().left -
				table.bodyScrollable
					.querySelector(".report-group-span-cell")
					.getBoundingClientRect().left
		);
	});
	expect(serial_start).toBeLessThan(2);
	let measured = await geometry();
	expect(measured.name_width).toBeLessThan(430);
	expect(Math.abs(measured.title_end - measured.total_start)).toBeLessThan(2);
	expect(Math.abs(measured.total_start - measured.detail_start)).toBeLessThan(2);
	const handle = page.locator(`.dt-cell--header-${measured.name_index} .dt-cell__resize-handle`);
	await handle.hover();
	const bounds = await handle.boundingBox();
	await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
	await page.mouse.down();
	await page.mouse.move(bounds.x + bounds.width / 2 + 65, bounds.y + bounds.height / 2, {
		steps: 5,
	});
	await page.mouse.up();
	await expect
		.poll(async () => (await geometry()).name_width)
		.toBeGreaterThan(measured.name_width + 40);
	measured = await geometry();
	expect(Math.abs(measured.title_end - measured.total_start)).toBeLessThan(2);
	expect(Math.abs(measured.total_start - measured.detail_start)).toBeLessThan(2);
	await page.setViewportSize({ width: 900, height: 900 });
	await page.evaluate(() => {
		const table = cur_list.datatable;
		const trailing = table.datamanager.getColumns().find((col) => col.field === "issingle");
		table.datamanager.updateColumn(trailing.colIndex, { width: 700 });
		table.columnmanager.setColumnHeaderWidth(trailing.colIndex);
		table.columnmanager.setColumnWidth(trailing.colIndex);
		table.bodyScrollable.scrollLeft = 100;
	});
	await page.waitForFunction(() => cur_list.datatable.bodyScrollable.scrollLeft > 0);
	await expect
		.poll(async () => {
			const measured = await geometry();
			return Math.abs(measured.header_start - measured.total_start);
		})
		.toBeLessThan(2);
	measured = await geometry();
	expect(Math.abs(measured.title_end - measured.total_start)).toBeLessThan(2);
	expect(Math.abs(measured.total_start - measured.detail_start)).toBeLessThan(2);
});

test("Grouping controls use compact labels, clear saved groups and toggle folding inline", async ({
	page,
	desk,
}) => {
	await page.goto("/desk/doctype/view/report");
	await desk.ready();
	await page.waitForFunction(() => cur_list.group_by_control && cur_list.datatable);
	// A saved configuration can be cleared without first opening its popover.
	if (await page.locator(".group-by-clear:visible").count()) {
		expect(await page.evaluate(() => Boolean(cur_list.group_by_control.wrapper))).toBe(false);
		await page.getByRole("button", { name: "Clear Grouping", exact: true }).click();
	}
	await expect(page.locator(".group-by-button .button-label")).toHaveText("Group");
	await expect(page.locator(".group-by-clear")).toBeHidden();
	await expect(page.locator(".group-by-fold-toggle")).toBeHidden();
	await expect(page.locator(".report-detail-group-toolbar")).toHaveCount(0);
	await expect(
		page.getByText(
			"Group totals include all matching records. Load more to see remaining details.",
			{ exact: true }
		)
	).toHaveCount(0);
	await page.waitForFunction(() => !frappe.model.user_settings.DocType?.Report?.group_by);
	await page.reload();
	await desk.ready();
	await expect(page.locator(".group-by-button .button-label")).toHaveText("Group");
	await page.locator(".group-by-button").click();
	await page.waitForFunction(() => cur_list.group_by_control.group_mode_select?.length);
	await page.locator(".group-mode:visible").selectOption("detail");
	await page.locator(".detail-group-field").first().selectOption("module");
	await page.locator(".add-detail-group-level").click();
	await page.locator(".detail-group-field").nth(1).selectOption("istable");
	await page.waitForFunction(
		() => JSON.stringify(cur_list.detail_group_summary?.fieldnames) === '["module","istable"]'
	);
	await expect(page.locator(".group-by-button .button-label")).toHaveText("Detail Groups2");
	await page.evaluate(() => cur_list.group_by_control.group_by_button.popover("hide"));
	await expect(page.locator(".group-by-selector > button:last-child")).toHaveClass(
		/group-by-clear/
	);
	const toggle = page.locator(".group-by-fold-toggle");
	await expect(toggle).toHaveAttribute("aria-label", "Collapse All");
	await toggle.click();
	await page.mouse.move(0, 0);
	await expect(toggle).toBeFocused();
	// A focused button must not paint over the next button's separator.
	expect(
		await page.locator(".group-by-clear").evaluate((button) => {
			const rect = button.getBoundingClientRect();
			return document
				.elementFromPoint(rect.x + 0.5, rect.y + rect.height / 2)
				?.closest("button")
				?.classList.contains("group-by-clear");
		})
	).toBe(true);
	expect(await page.evaluate(() => cur_list.detail_row_documents.filter(Boolean).length)).toBe(
		0
	);
	await expect(toggle).toHaveAttribute("aria-label", "Expand All");
	await toggle.click();
	expect(
		await page.evaluate(() => cur_list.detail_row_documents.filter(Boolean).length)
	).toBeGreaterThan(0);
	await expect(toggle).toHaveAttribute("aria-label", "Collapse All");
	await page.locator(".group-by-button").click();
	await page.locator(".group-mode:visible").selectOption("summary");
	await page.waitForFunction(() => Boolean(cur_list.group_by) && !cur_list.is_detail_grouped());
	await expect(page.locator(".group-by-button .button-label")).toHaveText("Summary Groups");
	await expect(toggle).toBeHidden();
	await page.getByRole("button", { name: "Clear Grouping", exact: true }).click();
	await expect(page.locator(".group-by-button .button-label")).toHaveText("Group");
	await page.waitForFunction(
		() =>
			!cur_list.fields.some(([field]) => field === "_aggregate_column") && !cur_list.group_by
	);
});

test("Detail grouping preserves column menus and group-safe column actions", async ({
	page,
	desk,
}) => {
	await page.goto("/desk/doctype/view/report");
	await desk.ready();
	await page.waitForFunction(() => cur_list.group_by_control && cur_list.datatable);
	if (await page.locator(".group-by-clear").isVisible()) {
		await page.locator(".group-by-clear").click();
		await page.waitForFunction(() => !cur_list.group_by_control.group_by);
	}
	await page.evaluate(async () => {
		await cur_list.filter_area.add("DocType", "name", "in", ["DocType", "DocField", "Report"]);
		cur_list.fields = [
			["name", "DocType"],
			["module", "DocType"],
			["istable", "DocType"],
			["issingle", "DocType"],
		];
		cur_list.start = 0;
		cur_list.page_length = 100;
		cur_list.last_args = null;
		await cur_list.refresh();
	});
	await page.locator(".group-by-button").click();
	await page.waitForFunction(() => cur_list.group_by_control.group_mode_select?.length);
	await page.locator(".group-mode:visible").selectOption("detail");
	while ((await page.locator(".detail-group-remove:visible").count()) > 1) {
		await page.locator(".detail-group-remove:visible").last().click();
	}
	await page.locator(".detail-group-field:visible").first().selectOption("module");
	await page.waitForFunction(
		() =>
			cur_list.is_detail_grouped() &&
			cur_list.data.length === 3 &&
			cur_list.detail_group_summary?.fieldname === "module" &&
			cur_list.datatable?.datamanager.getColumns().some((c) => c.field === "issingle")
	);
	await page.evaluate(() => cur_list.group_by_control.group_by_button.popover("hide"));
	const header = page.locator('.dt-row-header .dt-cell[data-col-index="2"]');
	await header.hover();
	await expect(header.locator(".dt-dropdown__toggle")).toBeVisible();
	await header.locator(".dt-dropdown__toggle").click();
	const menu = (label) =>
		page.locator(".dt-dropdown__list:visible").getByText(label, { exact: true });
	async function open_menu(field) {
		const index = await page.evaluate(
			(field) =>
				cur_list.datatable.datamanager.getColumns().find((c) => c.field === field)
					.colIndex,
			field
		);
		const cell = page.locator(`.dt-row-header .dt-cell[data-col-index="${index}"]`);
		await cell.hover();
		await cell.locator(".dt-dropdown__toggle").click();
	}
	const original_sort = await page.evaluate(() => [
		cur_list.sort_selector.sort_by,
		cur_list.sort_selector.sort_order,
	]);
	await expect(menu("Sort Ascending")).toBeVisible();
	await menu("Sort Ascending").click();
	await page.waitForFunction(
		() =>
			cur_list.sort_selector.sort_by === "name" &&
			cur_list.data.map((d) => d.name).join() === "DocField,DocType,Report"
	);
	expect(
		await page.evaluate(() => cur_list.detail_row_documents.filter(Boolean).map((d) => d.name))
	).toEqual(["DocField", "DocType", "Report"]);
	await open_menu("name");
	await menu("Sort Descending").click();
	await page.waitForFunction(
		() => cur_list.data.map((d) => d.name).join() === "Report,DocType,DocField"
	);
	expect(await row_numbers(page)).toEqual(["", 1, 2, 3]);
	await open_menu("name");
	await menu("Reset sorting").click();
	await page.waitForFunction(
		([field, order]) =>
			cur_list.sort_selector.sort_by === field &&
			cur_list.sort_selector.sort_order === order,
		original_sort
	);
	await open_menu("module");
	await menu("Freeze").click();
	await page.waitForFunction(
		() =>
			cur_list.datatable.datamanager.getColumns().find((c) => c.field === "module")
				.sticky === true
	);
	await open_menu("module");
	await menu("Unfreeze").click();
	await page.waitForFunction(
		() => !cur_list.datatable.datamanager.getColumns().find((c) => c.field === "module").sticky
	);
	await open_menu("issingle");
	await menu("Remove column").click();
	await page.waitForFunction(
		() =>
			!cur_list.columns.some((c) => c.field === "issingle") &&
			!cur_list.datatable?.datamanager.getColumns().some((c) => c.field === "issingle")
	);
	await open_menu("module");
	await menu("Add Column").click();
	await page.waitForFunction(() => window.cur_dialog?.fields_dict.column);
	await page.getByRole("listbox").getByText("Is Single", { exact: true }).click();
	await page.getByRole("button", { name: "Submit", exact: true }).click();
	await page.waitForFunction(
		() =>
			cur_list.columns.some((c) => c.field === "issingle") &&
			cur_list.datatable?.datamanager.getColumns().some((c) => c.field === "issingle")
	);
	await page.evaluate(() => {
		const manager = cur_list.datatable.datamanager;
		const first = manager.getColumns().find((c) => c.field === "module").colIndex;
		const second = manager.getColumns().find((c) => c.field === "istable").colIndex;
		cur_list.datatable.columnmanager.switchColumn(first, second);
	});
	await page.waitForFunction(
		() =>
			cur_list.columns[1].field === "istable" &&
			cur_list.datatable.datamanager.getColumns()[3].field === "istable"
	);
	expect(
		await page.locator(".report-group-span-cell").first().getAttribute("aria-colspan")
	).toBe(String(await page.evaluate(() => cur_list.columns.length + 1)));
	expect(await page.evaluate(() => cur_list.detail_row_documents.filter(Boolean).length)).toBe(
		3
	);
});
