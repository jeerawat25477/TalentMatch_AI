# Backend Specification: LangGraph & Agents

เอกสารนี้ระบุรายละเอียดโครงสร้างของระบบ Multi-Agent และ Logic การไหลของข้อมูล (Workflow) โดยใช้ LangGraph ในการพัฒนาระบบ **TalentMatch AI**

---

## 📂 1. โครงสร้างโฟลเดอร์ของ Agent
```text
backend/
├── app/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── state.py         # โครงสร้าง State
│   │   ├── graph.py         # เชื่อม Node และ Edges
│   │   └── nodes/           # โค้ดของแต่ละ Agent
│   │       ├── jd_analyzer.py
│   │       ├── resume_parser.py
│   │       ├── matcher.py
│   │       ├── bias_auditor.py
│   │       ├── planner.py
│   │       └── drafter.py
```

---

## 🗂️ 2. คำจำกัดความของ State (`app/agents/state.py`)
State คือหน่วยความจำหลักที่จะส่งต่อไปยังทุก Agent ในกราฟ:

```python
from typing import TypedDict, List, Dict, Any, Optional

class HRSystemState(TypedDict):
    # Inputs
    raw_jd: str
    raw_resumes: List[Dict[str, Any]]  # [{"filename": str, "content": str}]

    # Parsed Data
    analyzed_jd: Optional[Dict[str, Any]]
    parsed_resumes: List[Dict[str, Any]]

    # Evaluations
    evaluations: List[Dict[str, Any]]  # {"candidate_id": str, "fit_score": int, "gaps": list, "is_biased": bool}

    # Human-in-the-Loop Decisions
    hr_decision: Dict[str, str]  # {"candidate_id": "approved" | "rejected" | "pending"}
    hr_notes: Dict[str, str]

    # Outputs
    interview_plans: Dict[str, Any]
    email_drafts: Dict[str, Any]
```

---

## 🤖 3. รายละเอียดการทำงานของแต่ละ Node

### Node 1: JD Analyzer
*   **เป้าหมาย**: แปลง JD ดิบเป็นหัวข้อแยกประเภท
*   **Prompt**:
    ```text
    คุณคือผู้เชี่ยวชาญ HR จงดึงข้อมูลสำคัญจากประกาศรับสมัครงานนี้ให้อยู่ในรูปแบบต่อไปนี้:
    - job_title: ชื่อตำแหน่ง
    - min_experience_years: จำนวนปีขั้นต่ำ
    - required_skills: ทักษะที่ต้องมี (Must-have)
    - preferred_skills: ทักษะที่มีก็ดี (Nice-to-have)
    - education: ระดับการศึกษา
    ```

### Node 2: Resume Parser
*   **เป้าหมาย**: แปลงข้อความจาก PDF Resume ให้อยู่ในฟอร์แมต JSON เดียวกับ JD Analyzer

### Node 3: Candidate Matcher
*   **เป้าหมาย**: เปรียบเทียบข้อมูลที่แกะแล้วและคำนวณ Fit Score
*   **Logic**:
    *   วิเคราะห์ทักษะที่ขาดหาย (Gap Analysis)
    *   คำนวณคะแนน 0-100% โดยคำนึงถึง Required Skills (60%) และ Preferred Skills (40%)

### Node 4: Bias Auditor
*   **เป้าหมาย**: คัดกรองอคติ (Bias Check)
*   **Prompt**:
    ```text
    จงตรวจสอบผลการประเมินของผู้สมัครคนนี้ว่ามีการระบุข้อมูลอคติเกี่ยวกับ เพศ, อายุ, เชื้อชาติ, ศาสนา หรือสถาบันการศึกษาหรือไม่ ถ้ามี ให้ตัดข้อมูลอคติออกแล้วประเมินทักษะอย่างเที่ยงตรง
    ```

---

## 🔄 4. ระบบตัดสินใจ (Routing & Interrupt)
ในไฟล์ `app/agents/graph.py` จะมีส่วนเชื่อมต่อ Nodes และการตัดสินใจแบบมีเงื่อนไข (Conditional Edge):

```python
from langgraph.graph import StateGraph, END
from app.agents.state import HRSystemState
from app.agents.nodes import (
    analyze_jd, parse_resumes, match_candidates,
    audit_bias, plan_interviews, draft_emails
)

# 1. สร้าง Graph
workflow = StateGraph(HRSystemState)

# 2. เพิ่ม Node
workflow.add_node("jd_analyzer", analyze_jd)
workflow.add_node("resume_parser", parse_resumes)
workflow.add_node("matcher", match_candidates)
workflow.add_node("bias_auditor", audit_bias)
workflow.add_node("interview_planner", plan_interviews)
workflow.add_node("email_drafter", draft_emails)

# 3. กำหนดทิศทางเริ่มต้น
workflow.set_entry_point("jd_analyzer")
workflow.add_edge("jd_analyzer", "resume_parser")
workflow.add_edge("resume_parser", "matcher")
workflow.add_edge("matcher", "bias_auditor")

# 4. Router สำหรับตัดสินใจ (Conditional Edges)
def route_candidates(state: HRSystemState):
    # ดึงคะแนนประเมินล่าสุดของแคนดิเดต
    evals = state["evaluations"]
    for ev in evals:
        # หากคะแนนก้ำกึ่ง (50% - 70%) และ HR ยังไม่ได้เลือกทางเดิน
        if 50 <= ev["fit_score"] <= 70 and ev["candidate_id"] not in state["hr_decision"]:
            return "wait_for_hr"
    return "auto_process"

workflow.add_conditional_edges(
    "bias_auditor",
    route_candidates,
    {
        "wait_for_hr": END, # หยุดรันรอสัญญาณอนุมัติจาก HR
        "auto_process": "interview_planner" # ถ้านาย A คะแนนผ่านเกณฑ์ ส่งไปต่อทันที
    }
)

workflow.add_edge("interview_planner", "email_drafter")
workflow.add_edge("email_drafter", END)

# 5. Compile พร้อมระบบ Checkpointer (ระบบบันทึกความจำ)
# เพื่อรองรับการหยุดและทำต่อ (Human-in-the-Loop)
memory = SqliteSaver.from_conn_string(":memory:")
app = workflow.compile(checkpointer=memory, interrupt_before=["interview_planner"])
```
