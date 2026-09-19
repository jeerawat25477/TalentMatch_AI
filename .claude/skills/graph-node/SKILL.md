---
name: graph-node
description: อ่านก่อนเสมอเมื่อจะเพิ่ม แก้ หรือย้ายโหนดในกราฟ LangGraph ของ backend — ไฟล์ backend/app/agents/graph.py, state.py, models.py, runner.py, llm.py และ backend/app/agents/nodes/*.py (jd_analyzer, resume_parser, retriever, matcher, bias_auditor, planner, drafter) ใช้เมื่อผู้ใช้พูดทำนองว่า "เพิ่ม agent หรือโหนดใหม่", "แก้ prompt ของโหนด", "แก้ router หลัง bias_auditor", "แก้ลูป revise", "แก้ HITL รอ HR แล้วไปต่อ", "เปลี่ยนโมเดล Gemini" หรือภาษาอังกฤษเช่น LangGraph node, add agent, state, checkpointer, interrupt, resume, human in the loop, router, structured output, Pydantic schema, prompt รวมถึงตอนที่กราฟรันแล้วผลไม่เป็นอย่างที่คาดและต้องไล่ว่าโหนดไหนเขียนฟิลด์ไหน
---

# เพิ่มหรือแก้โหนดในกราฟ

กราฟรัน **ทีละผู้สมัครหนึ่งคน** โดยใช้ `thread_id = candidate_id` ดังนั้น `raw_resumes` `parsed_resumes` และ `evaluations` มีสมาชิกเดียวเสมอ แต่ยังคงรูปเป็น list ตามบรีฟเพื่อไม่ให้ state เปลี่ยนสัญญากับเอกสาร

ลำดับปัจจุบันคือ `jd_analyzer` → `resume_parser` → `retrieve_similar` → `matcher` → `bias_auditor` → router → (`interview_planner` หรือ `email_drafter`) → END พร้อมเส้นย้อนกลับ `revise` ไปที่ `matcher`

เส้นทางไฟล์ในเอกสารนี้นับจากรากของ repo ส่วนคำสั่งที่รันในคอนเทนเนอร์ใช้เส้นทางของคอนเทนเนอร์ ซึ่งมี `backend/` เป็นรากอยู่แล้ว

## เช็กลิสต์เมื่อเพิ่มโหนดใหม่

1. เพิ่มฟิลด์ที่ต้องใช้ใน `backend/app/agents/state.py` แล้วไล่ดูทุกโหนดที่อ่านฟิลด์นั้น `HRSystemState` เป็นนิยามเดียวของทั้งระบบ การมีสำเนาที่สองแปลว่าอีกไม่นานสองฝั่งจะไม่ตรงกัน
2. เขียนโหนดใน `backend/app/agents/nodes/` เป็นฟังก์ชันบริสุทธิ์ รับ state แล้วคืน dict เฉพาะฟิลด์ที่เปลี่ยน คืนทั้งก้อนจะทับงานของโหนดอื่นที่รันคู่กัน
3. ถ้าโหนดเรียก LLM ให้นิยาม Pydantic v2 model ใน `backend/app/agents/models.py` แล้วเรียกผ่าน `structured_invoke` การ parse ข้อความอิสระเองจะพังเงียบตอนโมเดลเปลี่ยนรูปประโยค
4. export ใน `backend/app/agents/nodes/__init__.py` แล้วต่อ `add_node` กับ `add_edge` ใน `backend/app/agents/graph.py`
5. **อัปเดต `COST_BY_KIND` ใน `backend/app/job_queue.py`** ถ้าโหนดเพิ่มจำนวน chat call ตัวเลขชุดนี้วัดจากการรันจริง ไม่ใช่ประมาณ เพราะถ้าประมาณต่ำไป worker จะเริ่มงานแล้วตายกลางทางด้วย 429 ซึ่งเสีย call ที่จ่ายไปแล้วฟรี ๆ
6. เขียนเทสใน `backend/tests/` โดย mock LLM ดูแบบอย่างจาก `backend/tests/test_bias_loop.py` และ `backend/tests/test_retriever.py`
7. รัน `docker compose exec -T backend python -m pytest tests/ -q`

## สิ่งที่เคยพังมาแล้ว และเหตุผลที่โค้ดเป็นแบบนี้

**โหนดที่ปิดได้ต้องยังอยู่ในกราฟ** `retrieve_similar` ตอน `RAG_ENABLED` ปิดจะคืนค่าว่าง ไม่ใช่ถูกถอดออกจากกราฟ เพราะรูปกราฟที่เปลี่ยนทำให้ checkpoint ที่บันทึกไว้ก่อนหน้าใช้ต่อไม่ได้ โหนดใหม่ที่มีสวิตช์ควรทำแบบเดียวกัน

**คำตัดสินของ HR มาก่อนคะแนนเสมอ** ใน `route_candidates` ต้องเช็ค `hr_decision` ก่อน `bias_revision_pending` และก่อนคะแนน นี่คือจุดที่ทำให้คำว่ามนุษย์มีอำนาจสูงสุดเป็นจริง ถ้าสลับลำดับ คนจะถูกลูปตรวจอคติขังไว้โดยที่ปุ่มบนหน้าเว็บดูเหมือนทำงาน

**ลูป critique/revise จำกัดหนึ่งรอบ** เข้าได้ต่อเมื่อ `audit_status == "flagged"` และ auditor ระบุเกณฑ์มาจริง โดย `MAX_BIAS_REVISIONS = 1` ใน `backend/app/agents/nodes/bias_auditor.py` คุมผ่าน `bias_revision_count` ไม่มีเพดานแปลว่าค่าใช้จ่ายต่อผู้สมัครหนึ่งคนไม่มีขอบเขต

**อย่าต่อข้อความสะสมลงใน `audit_log`** การตรวจรอบสองเขียนทับทั้งฟิลด์ ร่องรอยของลูปจึงต้องเก็บใน `evaluation["bias_revision"]` ซึ่ง `matcher` เป็นผู้เขียน ถ้าไม่เก็บ หน้าเว็บจะเห็นแต่คะแนนหลังแก้ แล้วลูปทั้งลูปจะหายไปจากสายตา HR

**HITL มีสองกรณี และต้องรองรับทั้งคู่ตลอดไป** ดู `runner.resume_after_decision` กรณีแรกคือกราฟพักอยู่ที่ interrupt ให้เขียนคำตัดสินแล้วเดินต่อ กรณีที่สองคือกราฟจบไปแล้ว ต้องใช้ `update_state(..., as_node="bias_auditor")` ย้อนกลับไปหลัง auditor เพื่อให้ router ตัดสินใหม่ แล้ว `_drive_to_end` เดินออกจนจบ เพราะ interrupt จะยิงอีกครั้งระหว่างทาง เรียก `invoke` ครั้งเดียวจึงไม่พอ ตอนที่ยังไม่มีกิ่งย้อน HR กู้คนที่คะแนนต่ำกว่า 50 ไม่ได้เลย ทั้งที่ API ตอบ 200 และหน้าเว็บบอกว่าสำเร็จ

**กราฟต้องไม่รันใหม่จากจุดเริ่ม** การรันใหม่คือการจ่ายค่า LLM ทุก call ซ้ำและทำให้ context ที่สะสมไว้หาย การอนุมัติคนที่พักอยู่ควรกินพอดี 2 call คือ planner กับ drafter ส่วนการปฏิเสธคนที่จบแล้วกิน 1 call

**ผลของ planner ต้องลง DB ทันทีที่มันเสร็จ ไม่ใช่ตอนกราฟจบ** เดินกราฟช่วงหลังผ่าน `runner._advance` ซึ่งใช้ `stream(stream_mode="updates")` แล้วเรียก `_persist_plan` ทันทีที่เห็นก้อนของ `interview_planner` เคยมีผู้สมัครที่ HR อนุมัติ planner สร้างคำถามเสร็จ แต่ drafter ล้มเพราะโควตา คำถามที่จ่ายเงินไปแล้วค้างอยู่ใน checkpoint ไม่เคยถึงหน้าเว็บ และสถานะยังบอกว่ารอ HR

**ห้าม `invoke(ข้อมูลตั้งต้น)` บน thread ที่มี checkpoint อยู่แล้ว** LangGraph จะเริ่มใหม่จาก entry ทั้งที่งานเดิมค้างอยู่ งาน `process` ที่คิวลองใหม่จึงต้องผ่าน `runner._resume_point` ก่อน แล้วเดินต่อจากโหนดที่ค้าง และห้ามเรียก `_persist_evaluation` ซ้ำเมื่อมีแถวอยู่แล้ว เพราะมันลบแถวเดิมทิ้งพร้อม `email_sent_at`

**`update_state` ต้องระบุ `as_node` เองทุกครั้ง** ถ้า checkpoint ล่าสุดเกิดจาก `update_state` รอบก่อน เช่นย้อนแล้ว planner ล้ม LangGraph จะเดาโหนดผิดจน `next` ว่าง กราฟดูเหมือนจบ และคิวนับว่าสำเร็จทั้งที่ไม่ได้ทำอะไร `resume_after_decision` จึงใช้ `bias_auditor` เมื่อจบแล้วหรือค้างที่ planner และใช้ `interview_planner` เมื่อค้างที่ drafter

**สถานะ "ค้างกลางทาง" ต้องแยกจาก "รอ HR"** `runner.resolve_graph_status` คืน `interrupted` เมื่อกราฟไม่จบและไม่ได้พักรอคำตัดสินจริง HR สั่งทำต่อได้ที่ `POST /api/v1/candidates/{id}/resume` ซึ่งเข้าคิวด้วย kind เดิม ส่วน router ต้องทับเป็น `processing` เมื่อคนนั้นกำลังรันหรือรอคิว ไม่งั้นปุ่มจะกะพริบให้กดซ้ำ

**checkpoint อาจถือเกณฑ์เก่า** HR แก้เกณฑ์ทักษะของตำแหน่งได้หลังกราฟเดินไปแล้ว (`app/criteria_edit.py` เขียนคะแนนใหม่ลง DB แต่ไม่แตะ checkpoint) `resume_after_decision` จึงเรียก `_fresh_screening` เติม `analyzed_jd` และ `evaluations[0]` (เฉพาะ fit_score/gaps) จาก DB ลงใน `update_state` ครั้งเดียวกับคำตัดสิน ไม่งั้น planner จะตั้งคำถามจากทักษะที่ HR ตัดออกไปแล้ว · `_continue_candidate` ยังไม่ได้ทำแบบนี้ (กันไว้ด้วย 409 ตอนแก้เกณฑ์)

**state สะสมข้ามการย้อน** รอบใหม่ที่เดินไปทางปฏิเสธจะไม่แวะ planner ดังนั้น `_persist_outputs` ต้องล้าง `interview_plan` เก่าทิ้งเมื่อร่างที่ได้เป็นอีเมลปฏิเสธ ไม่งั้นหน้าเว็บจะโชว์คำถามสัมภาษณ์ของคนที่เพิ่งถูกปฏิเสธ

**checkpointer ต้องเป็น `PostgresSaver`** บรีฟ `brief/backend_langgraph.md` แสดง `SqliteSaver.from_conn_string(":memory:")` ไว้เป็นตัวอย่างประกอบเท่านั้น state ในหน่วยความจำตายตอนรีสตาร์ตซึ่งทำให้ HITL ใช้ไม่ได้จริง

**การเรียกกราฟทุกจุดควรส่ง config แบบเดียวกับ `runner._config`** คือ `run_name`, `tags` และ `metadata.candidate_id` ไม่งั้น trace ใน LangSmith จะไม่มีชื่อและตามหาผู้สมัครรายนั้นไม่เจอ

**นับโควตาที่ `structured_invoke_once` จุดเดียว** โหนดจึงไม่ควรสร้าง `ChatGoogleGenerativeAI` เรียกเอง เพราะ call นั้นจะไม่ถูกนับแล้ว worker จะคิดว่าโควตายังเหลือ

**เลือกตัวเรียกให้ตรงกับสถานการณ์** endpoint ที่มีคนนั่งรอหน้าจอใช้ `structured_invoke_once` ซึ่งไม่ retry เพื่อให้รู้ผลเร็ว ส่วนงานเบื้องหลังใช้ `structured_invoke` ที่มี backoff เพราะไม่มีใครรออยู่

## เรื่องอคติ

`jd_analyzer` เป็นด่านแรก prompt ของมันรับเฉพาะสิ่งที่ผู้สมัครทำได้เข้า `required_skills` และ `preferred_skills` เกณฑ์อย่างอายุหรือเพศจึงถูกทิ้งตั้งแต่ต้นทาง กลไกที่ทำงานจริงคือ `bias_auditor` ได้รับ `raw_jd` ซึ่งตัดที่ `_MAX_JD_CHARS` แล้วคืน `biased_jd_criteria` ซึ่งเป็นเกณฑ์ที่มีอคติแต่ไม่ใช่ทักษะ จึงตัดออกจากคะแนนไม่ได้เพราะมันไม่เคยเข้าไปในคะแนนตั้งแต่แรก หน้าที่ของมันคือทำให้ HR มองเห็น ส่วนลูปตัดเกณฑ์เก็บไว้เป็นตาข่ายชั้นสองสำหรับสิ่งที่ไม่ใช่ทักษะแต่หลุด `is_skill()` เข้ามาได้
