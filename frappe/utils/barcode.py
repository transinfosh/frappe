import barcode
from barcode.writer import ImageWriter
import base64
from io import BytesIO


def get_barcode(data, barcode_type="Code128"):
	if not data:
		return ""
	try:
		# 使用 python-barcode 库生成
		EAN = barcode.get_barcode_class(barcode_type)
		rv = BytesIO()
		EAN(str(data), writer=ImageWriter()).write(rv)
		# 转换为 Base64 字符串供 <img> 标签使用
		return "data:image/png;base64," + base64.b64encode(rv.getvalue()).decode("utf-8")
	except Exception:
		return ""
