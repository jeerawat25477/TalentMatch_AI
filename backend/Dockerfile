# TalentMatch AI — Backend (FastAPI + LangGraph)
FROM python:3.12-slim

# ไม่เขียน .pyc, ให้ log ออกทันที (ไม่ buffer)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ติดตั้ง dependencies ก่อน copy โค้ด เพื่อใช้ layer cache
# psycopg[binary] มี libpq ในตัว (manylinux wheel) จึงไม่ต้องลง libpq-dev
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# copy ซอร์สโค้ดของแอป (app/ ตาม backend_fastapi.md)
COPY . .

EXPOSE 8000

# ไม่รันเป็น root — แอปไม่เขียนไฟล์ลงดิสก์เลย (PDF อ่านในหน่วยความจำ เก็บข้อความใน DB)
# จึงต้องการแค่สิทธิ์อ่านโค้ด · มี home ไว้ให้ไลบรารีเก็บแคช · ติดตั้งแพ็กเกจข้างบนยังเป็น root
RUN useradd --create-home --uid 1000 app
USER app

# จุดรันแอปหลักตาม brief: app/main.py -> ตัวแปร app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
