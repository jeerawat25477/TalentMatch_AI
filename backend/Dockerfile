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

# จุดรันแอปหลักตาม brief: app/main.py -> ตัวแปร app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
