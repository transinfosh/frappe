import barcode
from barcode.writer import ImageWriter
import base64
from io import BytesIO


def get_barcode(data, barcode_type: str = "Code128", write_text: bool = False, height: int = 15):
	"""生成条码图片.

	:param data: Content of barcode.
	:param barcode_type: Barcode type.
	:param write_text: Whether to write text under the barcode.
	:param height: Height of the barcode.
	"""
	if not data:
		return ""

	try:
		# 使用 python-barcode 库生成
		EAN = barcode.get_barcode_class(barcode_type)
		rv = BytesIO()

		writer_options = {
			"write_text": write_text,  # 这个选项会隐藏条码下方的文本标签
			"module_height": height,  # 条码模块高度
		}

		EAN(str(data), writer=ImageWriter()).write(rv, options=writer_options)
		# 转换为 Base64 字符串供 <img> 标签使用
		return "data:image/png;base64," + base64.b64encode(rv.getvalue()).decode("utf-8")
	except Exception:
		return ""
