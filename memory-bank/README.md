# 🧠 Memory Bank — TalentMatch AI

เอกสารส่งต่องาน (handoff) สำหรับ AI/นักพัฒนาที่มาทำต่อ **อ่านตามลำดับนี้ก่อนเริ่มงาน:**

1. [01_project_overview.md](01_project_overview.md) — โปรเจคคืออะไร, สถาปัตยกรรม, stack, **ข้อจำกัด Smart App Control (ต้องรู้)**
2. [02_progress.md](02_progress.md) — ✅ ทำอะไรเสร็จแล้ว · 🔜 ค้างอะไร · กับดัก
3. [03_environment.md](03_environment.md) — คำสั่ง Docker, endpoints, env vars, วิธีทดสอบ
4. [04_security.md](04_security.md) — รายงานช่องโหว่ตามมิติ + checklist ก่อน deploy จริง

**Source of truth ของสเปค:** [../brief/](../brief/) (ไทย) + [../CLAUDE.md](../CLAUDE.md)

## กติกาการอัปเดต Memory Bank
- ทำงานเสร็จเป็นก้อน → อัปเดต `02_progress.md` (ย้ายจาก 🔜 ไป ✅, บันทึกกับดักใหม่)
- เปลี่ยนคำสั่งรัน/env/endpoint → อัปเดต `03_environment.md`
- เปลี่ยนสถาปัตยกรรม/การตัดสินใจใหญ่ → อัปเดต `01_project_overview.md`
- เขียนกระชับ ให้คนที่ไม่เคยเห็น context นี้อ่านแล้วทำต่อได้ทันที
