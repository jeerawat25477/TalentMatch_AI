"""กราฟสำหรับ LangGraph Studio (dev เท่านั้น) — ดูโหนดทำงานสด ๆ ทีละผู้สมัคร.

ใช้ `build_graph()` ตัวเดียวกับระบบจริง และจุดพักรอ HR ตรงเดิม ต่างกันแค่ **ไม่ผูก checkpointer**
เพราะ `langgraph dev` มีที่เก็บ state ของมันเอง (ในหน่วยความจำ) — ส่ง PostgresSaver เข้าไป
Studio จะปฏิเสธ และถ้าใช้ได้ก็จะไปปนกับ thread ของผู้สมัครจริง

รันใน Studio ไม่เขียนผลลงหน้าเว็บ HR และไม่ส่งอีเมล: การบันทึกอยู่ใน `runner` ไม่ได้อยู่ในกราฟ
แต่ Gemini ถูกเรียกจริง (~4 call ต่อรอบ) และนับโควตาตามปกติ

ข้อมูลเริ่มต้นของผู้สมัครที่มีอยู่แล้ว: `python -m scripts.studio_input <candidate_id>`
วิธีเปิดดู memory-bank (หัวข้อ LangGraph Studio)
"""
from app.agents.graph import build_graph

# ต้องตรงกับ get_graph() — tests/test_studio_graph.py ล็อกไว้
INTERRUPT_BEFORE = ["interview_planner"]

graph = build_graph().compile(interrupt_before=INTERRUPT_BEFORE)
