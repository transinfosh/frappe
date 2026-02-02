import base64
import pyqrcode
from io import BytesIO


def get_qrcode(data):
    """生成二维码图片.

    :param data: Content of QR code.
    """
    if not data:
        return ""

    try:
        qr = pyqrcode.create(data)
        buffer = BytesIO()
        qr.png(buffer, scale=5)
        encoded_storage = buffer.getvalue()

        base64_str = base64.b64encode(encoded_storage).decode("utf-8")
        return f"data:image/png;base64,{base64_str}"

    except Exception:
        return ""
