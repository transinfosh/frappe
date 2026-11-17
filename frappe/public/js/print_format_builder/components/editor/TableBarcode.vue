<template>
	<span v-if="invalid && column.barcode_format !== 'QR'" class="text-muted">{{
		__("Invalid value for {0}", [column.barcode_format])
	}}</span>
	<FieldPreviewBarcode
		v-else-if="!invalid && value !== ''"
		:key="column.barcode_format + ':' + value"
		:df="barcode"
	/>
</template>

<script setup>
import { computed } from "vue";
import FieldPreviewBarcode from "./FieldPreviewBarcode.vue";

const props = defineProps(["column", "row"]);
const value = computed(() => {
	const raw = props.row[props.column.barcode_field || props.column.fieldname];
	return raw == null ? "" : String(raw);
});
const invalid = computed(() => {
	if (value.value === "") return false;
	if (value.value.length > 2000) return true;
	if (props.column.barcode_format === "CODE39") return !/^[A-Z0-9 .$/+%\-]+$/.test(value.value);
	if (props.column.barcode_format === "CODE128") return !/^[\x20-\x7e]+$/.test(value.value);
	return props.column.barcode_format !== "QR";
});
const barcode = computed(() => ({
	custom: true,
	fieldtype: "Barcode",
	barcode_format: props.column.barcode_format,
	barcode_value: value.value,
	width: `${Math.max(40, Math.min(300, parseInt(props.column.barcode_width) || 100))}px`,
	show_text: props.column.barcode_show_text !== false,
	barcode_margin: 10,
}));
</script>
