// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
// MIT License. See license.txt

export function get_fit_column_widths(grid, fieldnames) {
	// Use loaded documents, not the current page, filter, or selected-row view.
	const data = grid.frm
		? grid.frm.doc[grid.df.fieldname] || []
		: grid.df.data || grid.data || [];
	const context = document.createElement("canvas").getContext("2d");
	const template = document.createElement("template");
	const widths = {};
	const masked_fields = frappe.get_meta(grid.doctype)?.masked_fields || [];

	for (const fieldname of fieldnames) {
		const df = grid.fields_map[fieldname];
		if (!can_measure(df, grid)) continue;

		const header = grid.header_row.columns[fieldname]?.[0] || grid.wrapper[0];
		const cell = grid.wrapper
			.find(".grid-body .grid-static-col")
			.filter((_, element) => element.dataset.fieldname === fieldname)[0];
		const header_style = getComputedStyle(header);
		const cell_style = getComputedStyle(cell || header);
		const measure = (html, style, bold = false) => {
			// Parsing in a template is inert: formatter markup must not load resources
			// or run event handlers just to measure a column.
			template.innerHTML = cstr(html);
			template.content.querySelectorAll("script, style").forEach((node) => node.remove());
			template.content.querySelectorAll("br").forEach((node) => node.replaceWith("\n"));
			bold ||= !!template.content.querySelector("b, strong, .bold");
			context.font = `${style.fontStyle} ${bold ? "bold" : style.fontWeight} ${
				style.fontSize
			} ${style.fontFamily}`;
			context.letterSpacing = style.letterSpacing;
			const text = template.content.textContent || "";
			let width = 0;
			for (const line of text.split("\n")) {
				width = Math.max(width, context.measureText(line.replace(/\s+/g, " ")).width);
			}
			// Reserve space for standard checkboxes and formatter icons without
			// mounting controls or duplicating the formatted DOM.
			width += template.content.querySelectorAll("input, svg, img").length * 20;
			return (
				width +
				parseFloat(style.paddingLeft || 0) +
				parseFloat(style.paddingRight || 0) +
				4
			);
		};
		const label = frappe.utils.escape_html(__(df.label || fieldname, null, df.parent));
		let width = measure(label + (df.reqd ? " *" : ""), header_style);
		if (df.fieldtype === "Button") {
			width = Math.max(width, measure(label, cell_style) + 24);
		}

		for (const doc of data) {
			// Respect row-specific options and visibility without creating GridRows.
			const row_df = {
				...df,
				...frappe.meta.docfield_copy[grid.doctype]?.[doc.name]?.[fieldname],
			};
			if (!can_measure(row_df, grid)) continue;
			if (row_df.depends_on) {
				// fn: dependencies trigger form events; measuring must not execute them.
				if (typeof row_df.depends_on === "string" && row_df.depends_on.startsWith("fn:")) {
					continue;
				}
				if (
					!grid.header_row.evaluate_depends_on_value.call(
						{ doc, frm: grid.frm },
						row_df.depends_on
					)
				) {
					continue;
				}
			}

			// Never measure a newly entered password or masked value in plain text.
			const html =
				df.fieldtype === "Password" || masked_fields.includes(fieldname)
					? "********"
					: grid.header_row._format_static_value(doc[fieldname], row_df, doc);
			// Off-page rows have not evaluated mandatory dependencies yet. Match the
			// bold required-cell display without mutating their cached DocFields.
			let required = row_df.reqd;
			if (row_df.mandatory_depends_on) {
				const dependency = row_df.mandatory_depends_on;
				required =
					(typeof dependency === "string" && dependency.startsWith("fn:")) ||
					grid.header_row.evaluate_depends_on_value.call(
						{ doc, frm: grid.frm },
						dependency
					);
			}
			width = Math.max(width, measure(html, cell_style, row_df.bold || required));
			if (grid.clamp_column_width(Math.ceil(width)) < width) break;
		}
		widths[fieldname] = grid.clamp_column_width(Math.ceil(width));
	}
	return widths;
}

function can_measure(df, grid) {
	return (
		df &&
		!df.hidden &&
		!frappe.model.layout_fields.includes(df.fieldtype) &&
		(!grid.frm || grid.frm.get_perm(df.permlevel, "read"))
	);
}
