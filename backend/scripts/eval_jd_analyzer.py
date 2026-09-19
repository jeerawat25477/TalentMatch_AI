"""วัด jd_analyzer กับ Gemini จริง — ชุดประกาศทดสอบพร้อมผลที่ควรได้ แล้วบอกผ่าน/ไม่ผ่าน.

เทสใน tests/test_jd_analyzer_prompt.py พิสูจน์กติกาจัดฝั่ง (โค้ด) ได้ครบ แต่พิสูจน์ไม่ได้ว่าโมเดล
ติดป้ายถูก — สคริปต์นี้คือส่วนนั้น **รันทุกครั้งที่แก้ PROMPT หรือเปลี่ยน GEMINI_DEFAULT_MODEL**
ผลที่วัดไว้: memory-bank/06_scoring_criteria.md

ไม่เขียน DB เลย · กิน chat quota 1 call ต่อประกาศต่อรอบ (ถูกนับใน llm_quota_usage ตามปกติ)

    # ชุดประกาศในไฟล์นี้ (6 call)
    docker compose exec backend python scripts/eval_jd_analyzer.py
    # + ประกาศของตำแหน่งจริงใน DB, รันซ้ำ 2 รอบเพื่อดูความนิ่ง, เก็บป้ายดิบไว้
    docker compose exec backend python scripts/eval_jd_analyzer.py --db --repeat 2 --out /tmp/jd.jsonl
    # จัดฝั่งใหม่จากป้ายที่เก็บไว้ ไม่เรียก LLM — ใช้ตอนแก้ to_requirement
    docker compose exec backend python scripts/eval_jd_analyzer.py --replay /tmp/jd.jsonl
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.models import JDExtraction  # noqa: E402
from app.agents.nodes.jd_analyzer import extract_jd, to_requirement  # noqa: E402
from app.agents.skills import canonical  # noqa: E402

# expect: req_has = ต้องอยู่ฝั่งต้องมี · pref_has = ต้องอยู่ฝั่งอยากได้ · not_req = ห้ามอยู่ฝั่งต้องมี
#         nowhere = ห้ามโผล่ฝั่งไหน (เทียบ substring ไม่สนตัวพิมพ์) · req_max = ต้องมีไม่เกินกี่ข้อ
CASES = {
    "backend_th_sectioned": (
        """ตำแหน่ง: Backend Developer

หน้าที่
- พัฒนาและดูแล REST API ของระบบสมาชิก
- ทำงานร่วมกับทีม Frontend และ Product Owner

คุณสมบัติ
- ประสบการณ์ Python อย่างน้อย 2 ปี
- ใช้ FastAPI และ PostgreSQL ได้
- เข้าใจ Docker
- มีประสบการณ์ Redis จะพิจารณาเป็นพิเศษ""",
        {"req_has": ["Python", "FastAPI", "PostgreSQL", "Docker"], "pref_has": ["Redis"],
         "nowhere": ["product owner"]},
    ),
    "thai_or_example_namely": (
        """ตำแหน่ง DevOps Engineer
หน้าที่
- ดูแลระบบ monitoring และ logging ของบริษัท
- ปรับปรุง performance ของระบบ
คุณสมบัติ
- ใช้ Linux และ Git ได้คล่อง
- มีประสบการณ์ CI/CD
- ใช้ cloud อย่างใดอย่างหนึ่ง: AWS, Azure หรือ GCP
- รู้จักเครื่องมือ IaC เช่น Terraform, Pulumi
- เครื่องมือ container ได้แก่ Docker และ Kubernetes
- มีความรู้ TCP/IP
- มีประสบการณ์ Ansible จะพิจารณาเป็นพิเศษ""",
        {"req_has": ["Linux", "Git", "CI/CD", "Docker", "Kubernetes", "TCP/IP"],
         "pref_has": ["AWS", "Azure", "GCP", "Terraform", "Pulumi", "Ansible"],
         "not_req": ["monitoring", "logging"]},
    ),
    "bias_th": (
        """รับสมัคร Backend Developer
คุณสมบัติ
- เพศชาย อายุไม่เกิน 30 ปี
- จบจากมหาวิทยาลัยชั้นนำ สาขาวิทยาการคอมพิวเตอร์
- มีประสบการณ์ Python และ Django อย่างน้อย 3 ปี
- ใช้ PostgreSQL ได้""",
        {"req_has": ["Python", "Django", "PostgreSQL"],
         "nowhere": ["ชาย", "อายุ", "มหาวิทยาลัย", "วิทยาการคอมพิวเตอร์"]},
    ),
    "short_unsectioned_en": (
        "Looking for a Frontend Developer with React, TypeScript and Tailwind CSS. "
        "Next.js experience is a plus.",
        {"req_has": ["React", "TypeScript", "Tailwind CSS"], "pref_has": ["Next.js"]},
    ),
    "duties_only_en": (
        """Develop AI services using ML and GenAI technologies.
Build and maintain data workflows to support automation.
Collaborate with data scientists and product owners.
Integrate LLMs using frameworks such as LangChain and LangGraph.""",
        {"req_max": 0, "pref_has": ["LangChain", "LangGraph"],
         "nowhere": ["data scientists", "product owners", "workflows"]},
    ),
    # ประกาศจริงจาก JobsDB (ผู้ใช้ส่งมา 2026-09-19)
    "jobsdb_ai_architect": (
        """About the role
Analyze business requirements to select the most effective tools and LLMs for building Autonomous Agents. Design complex workflows, Multi-agent Systems, and high-performance RAG (Retrieval-Augmented Generation) frameworks to enable AI to make decisions and execute tasks with human-level precision. Serve as a technical advisor to establish the AI Roadmap, guiding the integration of AI solutions across various business units.
Key responsibilities

* Multi-agent Orchestration Design: Structuring multiple AI agents to work collaboratively (e.g., one agent researches data, one analyzes it, and another writes the report)
* Providing consultation to internal teams on business strategy and AI implementation
* Acting as a bridge between technology and the specific needs of various departments to ensure maximum ROI (Return on Investment) from AI initiatives
* Establishing robust standards and infrastructure to ensure that AI adoption across the organization is both secure and efficient

Qualification

* Bachelor's degree or higher in Computer Science, Computer Engineering, Information Technology, or fields related to Data Science / AI
* Generative AI Development (e.g., LangChain, LLM Application Building) or Machine Learning Engineering
* At least 3–5 years of experience in Software Engineering or Data Engineering
* Python Programming, Agentic Frameworks (LangChain, LangGraph, GoogleADK, CrewAI)
* Strong communication and consulting skills with the ability to translate business requirements into technical solutions
* Highly proactive with a passion for staying up-to-date in the rapidly evolving landscape of AI technology""",
        {"req_has": ["Python"], "not_req": ["LangChain", "LangGraph", "CrewAI", "GoogleADK"],
         "nowhere": ["communication", "consulting", "computer science"]},
    ),
}

# ผลที่ควรได้ของตำแหน่งจริงใน DB (ใช้กับ --db) · key = 8 ตัวแรกของ job id
DB_EXPECT = {
    "6c0d205a": {"req_has": ["Python", "SQL", "Prompt Engineering", "RAG", "Fine-tuning", "Docker",
                             "Kubernetes", "Git", "CI/CD"],
                 "not_req": ["PyTorch", "TensorFlow", "AWS", "Microsoft Azure", "Google Cloud Platform",
                             "LangChain", "Pinecone"]},
    "7b44445d": {"req_max": 3, "not_req": ["monitoring", "logging", "experimentation", "quantitative research"],
                 "pref_has": ["LangChain", "LangGraph"]},
}


def _has(names: list[str], want: str) -> bool:
    return canonical(want) in {canonical(n) for n in names}


def check(req: list[str], pref: list[str], expect: dict) -> list[str]:
    fails = []
    fails += [f"ต้องมีขาด {w}" for w in expect.get("req_has", []) if not _has(req, w)]
    fails += [f"อยากได้ขาด {w}" for w in expect.get("pref_has", []) if not _has(pref, w)]
    fails += [f"{w} ไม่ควรอยู่ฝั่งต้องมี" for w in expect.get("not_req", []) if _has(req, w)]
    everything = " | ".join(req + pref).casefold()
    fails += [f"'{w}' ไม่ควรโผล่" for w in expect.get("nowhere", []) if w.casefold() in everything]
    if "req_max" in expect and len(req) > expect["req_max"]:
        fails.append(f"ต้องมี {len(req)} ข้อ เกิน {expect['req_max']}")
    return fails


def report(label: str, req: list[str], pref: list[str], expect: dict | None) -> bool:
    fails = check(req, pref, expect) if expect else []
    mark = "—" if expect is None else ("PASS" if not fails else "FAIL")
    print(f"[{mark}] {label}\n  ต้องมี ({len(req)}): {req}\n  อยากได้ ({len(pref)}): {pref}")
    for f in fails:
        print(f"    ✗ {f}")
    return not fails


def load_db_cases() -> dict:
    from app.database import get_conn

    with get_conn() as conn:
        rows = conn.execute("SELECT id, title, raw_text FROM jobs ORDER BY created_at").fetchall()
    return {f"db:{r['title']} {str(r['id'])[:8]}": (r["raw_text"], DB_EXPECT.get(str(r["id"])[:8]))
            for r in rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", action="store_true", help="รวมประกาศของตำแหน่งจริงใน DB")
    ap.add_argument("--repeat", type=int, default=1, help="รันกี่รอบต่อประกาศ (ดูความนิ่ง)")
    ap.add_argument("--only", help="รันเฉพาะประกาศที่ชื่อมีคำนี้")
    ap.add_argument("--out", help="เก็บป้ายดิบเป็น jsonl ไว้ replay")
    ap.add_argument("--replay", help="จัดฝั่งใหม่จาก jsonl ที่เก็บไว้ ไม่เรียก LLM")
    args = ap.parse_args()

    cases = dict(CASES)
    if args.db:
        cases.update(load_db_cases())

    ok = True
    if args.replay:
        for line in open(args.replay, encoding="utf-8"):
            row = json.loads(line)
            label = row["label"]
            if args.only and args.only not in label:
                continue
            raw_jd, expect = cases.get(label, (row.get("raw_jd"), None))
            r = to_requirement(JDExtraction(**row["labels"]), row.get("raw_jd") or raw_jd)
            ok &= report(f"{label} (replay #{row.get('run', 1)})", r.required_skills, r.preferred_skills, expect)
        return 0 if ok else 1

    print(f"model = {os.getenv('GEMINI_DEFAULT_MODEL', '(default)')}\n")
    out = open(args.out, "w", encoding="utf-8") if args.out else None
    unstable = []
    for label, (raw_jd, expect) in cases.items():
        if args.only and args.only not in label:
            continue
        seen = []
        for run in range(1, args.repeat + 1):
            req, labels = extract_jd(raw_jd)
            suffix = f" #{run}" if args.repeat > 1 else ""
            ok &= report(label + suffix, req.required_skills, req.preferred_skills, expect)
            seen.append(sorted(canonical(s) for s in req.required_skills))
            if out:
                out.write(json.dumps({"label": label, "run": run, "raw_jd": raw_jd,
                                      "labels": labels.model_dump()}, ensure_ascii=False) + "\n")
        if len({tuple(s) for s in seen}) > 1:
            unstable.append(label)
    if out:
        out.close()
    if unstable:
        print("\nไม่นิ่ง (ฝั่งต้องมีต่างกันระหว่างรอบ):", ", ".join(unstable))
    print("\nผลรวม:", "ผ่านทั้งหมด" if ok and not unstable else "มีรายการไม่ผ่าน")
    return 0 if ok and not unstable else 1


if __name__ == "__main__":
    sys.exit(main())
