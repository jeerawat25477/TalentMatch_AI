"""แพตช์สำหรับ image LangGraph Studio เท่านั้น (ถูก COPY เป็น sitecustomize.py ใน Dockerfile.studio).

Chrome ถามก่อนให้หน้า https (smith.langchain.com) เรียก localhost ด้วย preflight ที่มี
`Access-Control-Request-Private-Network` · langgraph dev ตั้งใจอนุญาต (PrivateNetworkMiddleware
แปะ header ให้) แต่ CORSMiddleware ของ starlette ≥1.x ตอบ 400 ไปก่อนแล้ว เพราะไม่ได้เปิด
`allow_private_network` และ CORS_CONFIG ของ langgraph-api ส่งคีย์นี้ต่อไม่ได้ (schema ตัดทิ้ง)
ผล: Studio ขึ้น "Failed to fetch" · แก้โดยให้ค่าดีฟอลต์เป็น True — พอร์ตผูก 127.0.0.1 อยู่แล้ว
ลบไฟล์นี้ได้เมื่อ langgraph-api แก้เอง (ทดสอบ: preflight ที่มี header นี้ต้องได้ 200)
"""
try:
    from starlette.middleware import cors as _cors

    _orig_init = _cors.CORSMiddleware.__init__

    def _init(self, *args, **kwargs):
        kwargs.setdefault("allow_private_network", True)
        _orig_init(self, *args, **kwargs)

    _cors.CORSMiddleware.__init__ = _init
except Exception:  # noqa: BLE001 — แพตช์ล้มต้องไม่ทำให้ Python ทั้งตัวเปิดไม่ขึ้น
    pass
