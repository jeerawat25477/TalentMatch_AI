---
name: api-endpoint
description: อ่านก่อนเสมอเมื่อจะเพิ่มหรือแก้ endpoint หรือ router ของ FastAPI แล้วต่อให้หน้าเว็บเรียกได้ — ไฟล์ backend/app/routers/*.py, backend/app/schemas.py, backend/app/main.py และฝั่ง frontend/lib/api.ts กับ frontend/lib/types.ts ใช้เมื่อผู้ใช้พูดทำนองว่า "เพิ่ม API", "เพิ่ม endpoint", "เพิ่ม router ใหม่", "เพิ่มฟิลด์ใน response", "หน้าเว็บเรียก backend ไม่ได้", "ขึ้น 401 หรือ CORS" หรือภาษาอังกฤษเช่น FastAPI route, APIRouter, Pydantic schema, response_model, JWT auth dependency, CORS, 409 conflict, SWR fetcher รวมถึงตอนที่ผู้ใช้วาง error จาก network tab หรือ traceback ของ FastAPI มาถาม
---

# เพิ่มหรือแก้ endpoint

งานนี้เป็นวงจรปิดสามขั้นเสมอ คือ schema แล้ว router แล้วตัวเรียกฝั่งหน้าเว็บ ขาดขั้นใดขั้นหนึ่งแล้วหน้าเว็บจะพังเงียบ เพราะ TypeScript ไม่มีทางรู้ว่า backend เปลี่ยนรูป response ไปแล้ว

เส้นทางไฟล์ในเอกสารนี้นับจากรากของ repo ส่วนคำสั่งที่รันในคอนเทนเนอร์ใช้เส้นทางของคอนเทนเนอร์ ซึ่งมี `backend/` เป็นรากอยู่แล้ว

## ลำดับงาน

1. นิยาม request และ response ใน `backend/app/schemas.py` เป็น Pydantic v2 การคืน dict เปล่าทำให้ฝั่งหน้าเว็บต้องเดารูปข้อมูลเอง
2. เขียน handler ใน `backend/app/routers/` โดยใส่ `response_model=` ทุกครั้ง
3. router ใหม่ต้อง import และ `app.include_router(...)` ใน `backend/app/main.py`
4. เพิ่ม type ใน `frontend/lib/types.ts` แล้วเพิ่มฟังก์ชันเรียกใน `frontend/lib/api.ts` ผ่าน `request<T>` เท่านั้น เพราะตัวนั้นแนบ Bearer token และจัดการ 401 ให้ครบทั้งแอปอยู่แล้ว
5. หน้าเว็บที่อ่านข้อมูลใช้ SWR โดยส่ง path เต็มเป็น key คู่กับ `fetcher`
6. รัน `docker compose exec -T backend python -m pytest tests/ -q` แล้วดู log ด้วย `docker compose logs -f backend`

## สิ่งที่เคยพังมาแล้ว และเหตุผลที่โค้ดเป็นแบบนี้

**router ใหม่ต้องมี `dependencies=[Depends(get_current_user)]` ที่ระดับ router** ไม่ใช่ไล่ใส่รายฟังก์ชัน มีแค่ `/health` กับ `/api/v1/auth/login` ที่ไม่ต้องล็อกอิน การลืมข้อนี้หนึ่งครั้งเท่ากับเปิดข้อมูลผู้สมัครทั้งหมดให้คนนอกอ่านได้

**ความลับไม่ผ่าน API** host และ password ของ IMAP หรือ SMTP อ่านจาก env เท่านั้น ถ้าหน้าเว็บต้องรู้ว่าตั้งค่าครบหรือยัง ให้คืนเป็น boolean แบบ `imap_configured` ดูแบบอย่างที่ `backend/app/routers/settings.py`

**งานที่ใช้เวลานานต้องเข้าคิว ไม่ใช่ให้ผู้ใช้รอในรีเควสต์** insert แถวใน `processing_queue` แล้วตอบ 202 เคยใช้ `BackgroundTasks` แล้วงานหายไปพร้อมคอนเทนเนอร์ที่รีสตาร์ต เหลือผู้สมัครที่ไม่มีผลวิเคราะห์และไม่มีอะไรมาทำต่อ ขณะที่หน้าเว็บยังหมุนคำว่ากำลังวิเคราะห์ค้างไว้ตลอดกาล

**อีเมลส่งไปที่ค่าที่ HR เห็นและยืนยันบนหน้าจอเท่านั้น** ไม่ส่งไปที่ `candidate.email` ที่ LLM อ่านมาจาก PDF ตรง ๆ เพราะที่อยู่นั้นมาจากไฟล์ที่คนนอกเป็นคนสร้าง

**origin ของหน้าเว็บต้องอยู่ใน CORS ของ `backend/app/main.py`** ตอนนี้อนุญาต `localhost:3000` และ `localhost:4000`

**เปลี่ยนรูป response แล้วแก้ `frontend/lib/types.ts` ในคอมมิตเดียวกัน** โดยเฉพาะฟิลด์ที่ UI ใช้ตัดสินใจอย่าง `queue_status` และ `graph_status` ถ้าแยกคอมมิต จะมีช่วงที่หน้าเว็บอ่านฟิลด์ที่ไม่มีอยู่จริงโดยไม่มี error ให้เห็น

**แมป error ให้ตรงความหมาย** 409 สำหรับสถานะที่ขัดกัน เช่น งานปิดรับแล้ว กราฟกำลังรัน หรือส่งอีเมลไปแล้ว 400 สำหรับไฟล์ที่รับไม่ได้ 413 สำหรับไฟล์ใหญ่เกิน และ 429 สำหรับการกดถี่เกิน ฝั่งหน้าเว็บอ่าน `detail` ไปแสดงตรง ๆ ข้อความจึงควรเขียนให้ HR อ่านรู้เรื่องทันที

**การลบต้องมีด่านกั้น** ดูแบบอย่างที่ `backend/app/routers/jobs.py::_deletion_blocker` และ `backend/app/routers/candidates.py::_candidate_deletion_blocker` และถ้าลบของที่มี checkpoint ให้เก็บ `candidate_id` ไว้ก่อน cascade แล้วเรียก `delete_thread` หลัง commit ลำดับนี้ตั้งใจให้ความล้มเหลวเหลือแค่ orphan ที่ไม่มีพิษ แทนที่จะทำลาย state ของงานที่ยังอยู่

**ตัวเลขที่ใช้ตัดสินใจมาจากแหล่งเดียว** เส้นแบ่งคะแนนมาจาก `backend/app/agents/bands.py` และต้นทุน call มาจาก `backend/app/job_queue.py::COST_BY_KIND` การเขียนซ้ำใน router คือจุดเริ่มของการที่ API กับกราฟตัดสินคนละแบบ

**แยก logic ออกเป็นฟังก์ชันบริสุทธิ์ในไฟล์เดียวกัน** ตามแพตเทิร์นที่มีอยู่แล้วอย่าง `_bulk_partition`, `_is_stalled` และ `_is_duplicate_upload` แล้วเขียนเทสให้มันโดยไม่ต้องต่อ DB ซึ่งทำให้กฎเหล่านั้นถูกตรวจได้ทุกครั้งที่รันเทส
