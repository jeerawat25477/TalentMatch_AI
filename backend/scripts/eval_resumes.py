"""วัดผลตามบรีฟข้อ 7 — การสกัดทักษะ การให้คะแนน ความเร็ว และค่าใช้จ่ายต่อการวิเคราะห์.

ชุดทดสอบ: เรซูเม่สาธิต 10 ไฟล์ใน demo_resumes/pdf (สร้างจาก generate.py จึงรู้คำตอบแน่นอน)
คำตอบที่ถูกอยู่ใน CASES ด้านล่าง (ผู้ใช้ตรวจตารางแล้ว 2026-10-12)

สิ่งที่วัด
  ก. resume_parser: Recall / Precision ของทักษะ + อ่านชื่อถูกไหม (ใช้ skills.matches เทียบ เหมือนตอนให้คะแนน)
  ข. การให้คะแนน: กลุ่มคะแนน (ผ่าน / รอ HR / ไม่ผ่าน) ตรงกับที่ควรได้ไหม · ข้อมูลส่วนตัวไม่มีผลกับคะแนน
  ค. ทั้งกราฟ 3 คน: จำนวน call, token, เวลาแยกตามโหนด (กราฟไม่มี checkpointer ไม่เขียน DB ไม่ส่งอีเมล)
  ง. --langsmith: อัปโหลด Dataset + Experiment ของผลที่วัดแล้ว (ไม่เรียก AI ซ้ำ · ไม่มีเวลา/token)
     --langsmith-live: เรียกตัวอ่านเรซูเม่จริง 9 ไฟล์ (18 call) — Experiment มีเวลาและ token ด้วย

⚠ เรียก Gemini จริง (~3 + 18×รอบ + ~12 call) · ถามเจ้าของงบก่อนรันทุกครั้ง
ผลดิบเก็บใน --out แล้วคิดตัวเลขใหม่ได้ด้วย --replay โดยไม่เสีย call

    docker cp demo_resumes/pdf talentmatch_backend:/tmp/demo_pdf
    docker compose exec backend python scripts/eval_resumes.py --pdf-dir /tmp/demo_pdf \\
        --rounds 2 --graph --out /tmp/eval_resumes.json --price-in 0.30 --price-out 2.50
    docker compose exec backend python scripts/eval_resumes.py --replay /tmp/eval_resumes.json --langsmith
    docker compose exec backend python scripts/eval_resumes.py --pdf-dir /tmp/demo_pdf --langsmith-live
"""
import argparse
import json
import re
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.bands import band  # noqa: E402
from app.agents.bias_rules import find_biased_phrases  # noqa: E402
from app.agents.skills import matches  # noqa: E402

AI_JOB_ID_PREFIX = "6c0d205a"  # ตำแหน่ง AI Engineer ที่มีอยู่ (ต้องมี 15 / อยากได้ 5) — ไม่เสีย call อ่านประกาศ

JDS = {
    "marketing": """ตำแหน่ง: Digital Marketing Executive

หน้าที่
- วางแผนและยิงโฆษณาออนไลน์ ดูแลงบประมาณรายเดือน
- วัดผลแคมเปญและทำรายงานให้ผู้บริหาร

คุณสมบัติ
- ประสบการณ์ 2 ปีขึ้นไปด้าน Digital Marketing
- ยิงโฆษณา Facebook Ads และ Google Ads ได้
- ใช้ Google Analytics วัดผลได้
- เข้าใจ SEO และ Content Marketing
- ใช้ Canva หรือ Adobe Photoshop ได้
- มีประสบการณ์ TikTok Ads จะพิจารณาเป็นพิเศษ""",
    "accountant": """ตำแหน่ง: นักบัญชี

คุณสมบัติ
- วุฒิปริญญาตรี สาขาบัญชี
- ปิดงบการเงินรายเดือนได้ เข้าใจมาตรฐาน TFRS for NPAEs
- ยื่นภาษี ภ.ง.ด.1, ภ.ง.ด.3, ภ.ง.ด.53 และ ภ.พ.30 ได้
- ใช้โปรแกรม Express หรือ SAP Business One ได้
- ใช้ Excel ได้ดี
- เป็นผู้ทำบัญชีที่ขึ้นทะเบียนแล้วจะพิจารณาเป็นพิเศษ""",
    "hr": """Position: HR Recruiter

Qualifications
- 2+ years of recruitment experience
- Sourcing on LinkedIn and JobsDB
- Structured interviewing
- Experience with an ATS such as Workday or SAP SuccessFactors
- Employer branding is a plus""",
}

PASS, REVIEW, FAIL = "pass", "review", "fail"

# file → (ชื่อที่ต้องอ่านได้, [(ตำแหน่ง, กลุ่มที่ยอมรับ)], ทักษะที่ต้องเจอ, ยอมรับได้, มีข้อมูลส่วนตัว)
CASES = {
    "ai_01_strong_fit_EN.pdf": (
        "Natthapong Srisuk", [("ai", {PASS})],
        ["Python", "SQL", "TypeScript", "PyTorch", "TensorFlow", "scikit-learn", "Hugging Face",
         "XGBoost", "OpenAI API", "Azure OpenAI", "Claude API", "LangChain", "LangGraph", "LlamaIndex",
         "RAG", "Prompt Engineering", "Fine-tuning", "AI Agents", "pgvector", "ChromaDB", "FAISS",
         "Azure", "AWS", "Docker", "Kubernetes", "Git", "CI/CD", "GitHub Actions", "PostgreSQL",
         "BigQuery", "Airflow"],
        ["Machine Learning", "LLM", "Llama", "AKS", "LoRA", "Hugging Face Transformers"], False),
    "ai_02_data_scientist_partial_TH.pdf": (
        "พิมพ์ชนก วงศ์ประเสริฐ", [("ai", {FAIL, REVIEW})],
        ["Python", "SQL", "R", "Machine Learning", "scikit-learn", "TensorFlow", "XGBoost", "AWS", "S3",
         "Redshift", "SageMaker", "Git", "Power BI", "Excel", "pandas"],
        ["ChatGPT", "OpenAI API", "Prompt Engineering", "Excel VBA"], False),
    "ai_03_new_grad_personal_info_TH.pdf": (
        "ธนกฤต ใจดี", [("ai", {FAIL, REVIEW})],
        ["Python", "SQL", "C++", "PyTorch", "Hugging Face", "Machine Learning", "Deep Learning",
         "LangChain", "OpenAI API", "Prompt Engineering", "RAG", "ChromaDB", "Git", "Linux",
         "Google Colab", "OpenCV"],
        ["Fine-tuning", "Computer Vision", "ResNet", "ResNet-50"], True),
    "ai_04_backend_career_switch_EN.pdf": (
        "Kittipat Rattanakorn", [("ai", {FAIL})],
        ["Java", "Kotlin", "Spring Boot", "SQL", "PostgreSQL", "Redis", "Kafka", "AWS", "EKS", "RDS",
         "S3", "Docker", "Kubernetes", "Git", "CI/CD", "Terraform", "ChatGPT", "GitHub Copilot",
         "OpenAI API"],
        ["GitHub Actions", "REST API", "REST APIs"], False),
    "ai_05_two_column_canva_style_EN.pdf": (
        "Supansa Thongdee", [("ai", {FAIL, REVIEW})],
        ["Python", "SQL", "TensorFlow", "Keras", "Deep Learning", "Computer Vision",
         "Google Cloud Platform", "Vertex AI", "Docker", "Git"],
        ["Machine Learning"], False),
    "mkt_01_digital_marketing_fit_TH.pdf": (
        "ณัฐธิดา แสงทอง", [("marketing", {PASS})],
        ["Facebook Ads", "Google Ads", "TikTok Ads", "SEO", "Google Analytics 4", "Looker Studio",
         "Content Marketing", "Copywriting", "Canva", "Adobe Photoshop"],
        ["Influencer Marketing", "Google Analytics"], False),
    "mkt_02_sales_to_marketing_partial_TH.pdf": (
        "วรเมธ บุญมา", [("marketing", {FAIL})],
        ["การเจรจาต่อรอง", "การนำเสนอ", "Microsoft Excel", "PowerPoint", "Facebook", "LINE OA"],
        ["ขับรถยนต์", "ใบขับขี่", "ขับรถยนต์ได้ มีใบขับขี่", "Sales", "การขาย", "Excel"], True),
    "acc_01_accountant_fit_TH.pdf": (
        "สุนิสา พรหมมา", [("accountant", {PASS}), ("ai", {FAIL})],
        ["ปิดงบการเงิน", "TFRS for NPAEs", "ภาษีอากร", "SAP Business One", "Express", "Microsoft Excel"],
        ["Pivot Table", "VLOOKUP", "กระทบยอดธนาคาร", "Excel", "ภ.ง.ด.", "ภ.พ.30"], False),
    "hr_01_recruiter_fit_EN.pdf": (
        "Chayanee Kaewmanee", [("hr", {PASS})],
        ["Recruitment", "Sourcing", "Interviewing", "Employer Branding", "LinkedIn Recruiter", "JobsDB",
         "Workday", "Excel", "Labor Protection Act"],
        ["Onboarding", "Structured interviewing", "LinkedIn", "ATS"], False),
}
SCANNED = "edge_01_scanned_image_only.pdf"
GRAPH_CASES = ["ai_01_strong_fit_EN.pdf", "ai_02_data_scientist_partial_TH.pdf", "ai_04_backend_career_switch_EN.pdf"]

# บรรทัดข้อมูลส่วนตัวในเรซูเม่ไทย — ใช้ทดสอบว่าลบออกแล้วคะแนนเท่าเดิม
_PERSONAL = re.compile(r"(เพศ|อายุ|ศาสนา|สถานภาพ|สัญชาติ|วันเกิด|สถานะทางทหาร)\s*:")


# ---------------- สูตร (บริสุทธิ์ — tests/test_eval_resumes.py) ----------------

def skill_scores(parsed: list[str], must: list[str], ok: list[str]) -> dict:
    """Recall = ทักษะที่ต้องเจอ หาเจอกี่ % · Precision = ที่ AI ตอบมา ถูกกี่ % (นับ "ยอมรับได้" เป็นถูก)."""
    owned = set(parsed)
    found = [m for m in must if matches(m, owned)]
    allowed = must + ok
    correct = [p for p in parsed if matches(p, set(allowed)) or any(matches(a, {p}) for a in allowed)]
    return {
        "recall": len(found) / len(must) if must else 1.0,
        "precision": len(correct) / len(parsed) if parsed else 0.0,
        "missed": [m for m in must if m not in found],
        "extra": [p for p in parsed if p not in correct],
    }


def same_name(got: str | None, want: str) -> bool:
    norm = lambda s: " ".join((s or "").casefold().split())  # noqa: E731
    return norm(got) == norm(want)


def strip_personal(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not _PERSONAL.search(l))


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = {s.casefold() for s in a}, {s.casefold() for s in b}
    return len(sa & sb) / len(sa | sb) if sa | sb else 1.0


# ---------------- ส่วนที่เรียก AI ----------------

def _usage(cb) -> tuple[int, int]:
    tin = sum(u.get("input_tokens", 0) for u in cb.usage_metadata.values())
    tout = sum(u.get("output_tokens", 0) for u in cb.usage_metadata.values())
    return tin, tout


def _criteria() -> dict:
    from app.agents.nodes.jd_analyzer import extract_jd
    from app.database import get_conn

    with get_conn() as conn:
        row = conn.execute(
            "SELECT parsed_criteria FROM jobs WHERE left(id::text, 8) = %s", (AI_JOB_ID_PREFIX,)
        ).fetchone()
    out = {"ai": row["parsed_criteria"]}
    for key, text in JDS.items():
        req, _ = extract_jd(text, once=True)
        out[key] = req.model_dump()
    return out


def _parse(text: str) -> dict:
    from langchain_core.callbacks import get_usage_metadata_callback

    from app.agents.nodes.resume_parser import parse_resumes

    with get_usage_metadata_callback() as cb:
        t0 = time.perf_counter()
        profile = parse_resumes({"raw_resumes": [{"candidate_id": "eval", "content": text}]})["parsed_resumes"][0]
        secs = time.perf_counter() - t0
    tin, tout = _usage(cb)
    return {"profile": profile, "secs": secs, "tokens_in": tin, "tokens_out": tout}


def _graph_run(text: str, analyzed: dict) -> dict:
    """ทั้งกราฟจริงแบบไม่มี checkpointer/interrupt — ไม่เขียน DB · 50–70 เดินต่อเหมือน HR อนุมัติ."""
    from langchain_core.callbacks import get_usage_metadata_callback

    from app.agents.graph import build_graph
    from app.agents.runner import initial_state
    from app.agents.llm import COMPLEX_MODEL, DEFAULT_MODEL
    from app.llm_quota import used_today

    def calls_today() -> int:  # นับจากตัวนับโควตาจริงของระบบ (structured_invoke_once บันทึกทุก call)
        return sum(used_today(m) for m in {DEFAULT_MODEL, COMPLEX_MODEL})

    graph = build_graph().compile()
    before = calls_today()
    nodes: list[dict] = []
    with get_usage_metadata_callback() as cb:
        t0 = last = time.perf_counter()
        # candidate_id ต้องเป็น UUID — retrieve_similar ส่งเข้า SQL (รอบ 2026-10-12 ใช้ "eval" แล้วโหนดนี้ล้ม
        # เงียบ ๆ เวลาของโหนดนั้นจึงไม่ใช่ของจริง) · uuid ใหม่ไม่ตรงใครในระบบ จึงไม่กันตัวเองผิดคน
        cid = str(uuid.uuid4())
        for update in graph.stream(initial_state(cid, "", analyzed, text), stream_mode="updates"):
            now = time.perf_counter()
            for name in update:
                nodes.append({"node": name, "secs": round(now - last, 2)})
            last = now
        total = time.perf_counter() - t0
    tin, tout = _usage(cb)
    return {"secs": round(total, 2), "nodes": nodes, "tokens_in": tin, "tokens_out": tout,
            "calls": calls_today() - before}


def collect(pdf_dir: Path, rounds: int, run_graph: bool) -> dict:
    from app.resume_ingest import is_unreadable_resume
    from app.utils.pdf_extractor import extract_text_from_pdf

    raw = {"criteria": _criteria(), "texts": {}, "parses": {}, "graph": {}}
    scanned = extract_text_from_pdf((pdf_dir / SCANNED).read_bytes())
    raw["scanned_rejected"] = is_unreadable_resume(scanned)
    for f in CASES:
        raw["texts"][f] = extract_text_from_pdf((pdf_dir / f).read_bytes())
    for r in range(rounds):
        for f in CASES:
            print(f"รอบ {r + 1} อ่าน {f} …", flush=True)
            raw["parses"].setdefault(f, []).append(_parse(raw["texts"][f]))
    if run_graph:
        for f in GRAPH_CASES:
            print(f"ทั้งกราฟ {f} …", flush=True)
            raw["graph"][f] = _graph_run(raw["texts"][f], raw["criteria"]["ai"])
    return raw


# ---------------- รายงาน ----------------

def report(raw: dict, price_in: float | None, price_out: float | None) -> dict:
    from app.agents.nodes.matcher import evaluate_skills

    crit = raw["criteria"]
    rows, recalls, precisions, names, bands_ok, bands_n, stab = [], [], [], [], 0, 0, []
    print("\n=== ก. สกัดทักษะ (รอบแรก) · ข. กลุ่มคะแนน ===")
    for f, (want_name, targets, must, ok, personal) in CASES.items():
        runs = raw["parses"][f]
        p = runs[0]["profile"]
        sc = skill_scores(p.get("skills") or [], must, ok)
        recalls.append(sc["recall"]); precisions.append(sc["precision"])
        names.append(same_name(p.get("full_name"), want_name))
        if len(runs) > 1:
            stab.append(jaccard(runs[0]["profile"].get("skills") or [], runs[1]["profile"].get("skills") or []))
        text = raw["texts"][f]
        line = f"{f[:28]:<28} R {sc['recall']:.0%}  P {sc['precision']:.0%}  ชื่อ {'✓' if names[-1] else '✗ ' + str(p.get('full_name'))}"
        for job, accept in targets:
            c = crit[job]
            res = evaluate_skills(c.get("required_skills") or [], c.get("preferred_skills") or [], p, text)
            got = band(res["fit_score"])
            okb = got in accept
            bands_ok += okb; bands_n += 1
            line += f" | {job}: {res['fit_score']} {got} {'✓' if okb else '✗ (ควร ' + '/'.join(sorted(accept)) + ')'}"
            if personal:
                res2 = evaluate_skills(c.get("required_skills") or [], c.get("preferred_skills") or [], p,
                                       strip_personal(text))
                line += " · ลบข้อมูลส่วนตัวแล้วคะแนน" + (" เท่าเดิม ✓" if res2["fit_score"] == res["fit_score"] else f" เปลี่ยน ✗ {res2['fit_score']}")
        leaked = [s for s in (p.get("skills") or []) if find_biased_phrases(s)]
        if leaked:
            line += f" · ⚠ ข้อมูลส่วนตัวหลุดเป็นทักษะ: {leaked}"
        print(line)
        if sc["missed"]:
            print(f"   หาไม่เจอ: {', '.join(sc['missed'])}")
        if sc["extra"]:
            print(f"   เดาเกิน/นอกตาราง: {', '.join(sc['extra'])}")
        rows.append({"file": f, **sc, "name_ok": names[-1]})

    n = len(CASES)
    summary = {
        "recall": sum(recalls) / n, "precision": sum(precisions) / n,
        "name_acc": sum(names) / n, "band_acc": bands_ok / bands_n,
        "stability": (sum(stab) / len(stab)) if stab else None,
        "scanned_rejected": raw.get("scanned_rejected"),
    }
    print("\n=== สรุป ===")
    print(f"Recall เฉลี่ย {summary['recall']:.0%} · Precision เฉลี่ย {summary['precision']:.0%} · "
          f"อ่านชื่อถูก {sum(names)}/{n} · กลุ่มคะแนนถูก {bands_ok}/{bands_n}")
    if summary["stability"] is not None:
        print(f"ความนิ่งระหว่าง 2 รอบ (ทักษะชุดเดียวกัน, Jaccard) เฉลี่ย {summary['stability']:.0%}")
    print(f"ไฟล์สแกน: {'ถูกปฏิเสธ ✓ ไม่เสีย call' if summary['scanned_rejected'] else '✗ ไม่ถูกปฏิเสธ'}")

    parses = [r for runs in raw["parses"].values() for r in runs]
    ps = sorted(r["secs"] for r in parses)
    print(f"\n=== ค. ความเร็ว/ค่าใช้จ่าย ===\nอ่านเรซูเม่ (2 call) {len(ps)} ครั้ง: "
          f"เฉลี่ย {sum(ps) / len(ps):.1f} วิ · ช้าสุด {ps[-1]:.1f} วิ · "
          f"token เฉลี่ย เข้า {sum(r['tokens_in'] for r in parses) / len(parses):.0f} / "
          f"ออก {sum(r['tokens_out'] for r in parses) / len(parses):.0f}")
    for f, g in raw.get("graph", {}).items():
        cost = ""
        if price_in is not None and price_out is not None:
            usd = g["tokens_in"] / 1e6 * price_in + g["tokens_out"] / 1e6 * price_out
            cost = f" · ≈ ${usd:.5f}"
        steps = " → ".join(f"{s['node']} {s['secs']}s" for s in g["nodes"])
        print(f"ทั้งกราฟ {f[:28]}: {g['calls']} call · {g['secs']} วิ · token {g['tokens_in']}/{g['tokens_out']}{cost}\n   {steps}")
    summary["rows"] = rows
    return summary


DATASET = "talentmatch-resume-eval"


def _dataset(client) -> str:
    """Dataset 9 ไฟล์ + คำตอบที่ถูก — สร้างครั้งแรกครั้งเดียว ใช้ร่วมกันทั้งโหมดอัปผลเก่าและโหมดรันจริง."""
    ds = next(iter(client.list_datasets(dataset_name=DATASET)), None) or client.create_dataset(
        DATASET, description="เรซูเม่สาธิต 9 ไฟล์ + คำตอบที่ถูก (บรีฟข้อ 7) — scripts/eval_resumes.py")
    have = {e.inputs.get("file") for e in client.list_examples(dataset_id=ds.id)}
    for f, (want_name, targets, must, ok, _) in CASES.items():
        if f not in have:
            client.create_example(inputs={"file": f}, outputs={"name": want_name, "must": must, "ok": ok},
                                  dataset_id=ds.id)
    return DATASET


def ev_recall(run, example):
    sc = skill_scores(run.outputs["profile"].get("skills") or [], example.outputs["must"], example.outputs["ok"])
    return {"key": "skill_recall", "score": sc["recall"]}


def ev_precision(run, example):
    sc = skill_scores(run.outputs["profile"].get("skills") or [], example.outputs["must"], example.outputs["ok"])
    return {"key": "skill_precision", "score": sc["precision"]}


def ev_name(run, example):
    return {"key": "name_correct", "score": int(same_name(run.outputs["profile"].get("full_name"), example.outputs["name"]))}


EVALUATORS = [ev_recall, ev_precision, ev_name]


def push_langsmith(raw: dict, summary: dict) -> None:
    """Dataset + Experiment ใน LangSmith จากผลที่วัดแล้ว — ไม่เรียก AI ซ้ำ (target คืนผลที่เก็บไว้).

    ข้อเสีย: ไม่มี call เกิดขึ้นตอนอัป หน้า Experiment จึงไม่มีเวลา/token — ใช้ --langsmith-live ถ้าต้องการ
    """
    from langsmith import Client, evaluate

    name = _dataset(Client())
    cached = {f: runs[0]["profile"] for f, runs in raw["parses"].items()}

    def target(inputs: dict) -> dict:
        return {"profile": cached[inputs["file"]]}

    evaluate(target, data=name, evaluators=EVALUATORS, experiment_prefix="resume-parser")
    print(f"\nอัปโหลด LangSmith แล้ว: dataset '{name}' + experiment 'resume-parser-…'")


def live_target(texts: dict[str, str], parse=None):
    """target ที่เรียกตัวอ่านเรซูเม่จริงทุกไฟล์ — LangSmith จับเวลา/token ของ Gemini ข้างในให้เอง."""
    if parse is None:
        from app.agents.nodes.resume_parser import parse_resumes as parse

    def target(inputs: dict) -> dict:
        state = {"raw_resumes": [{"candidate_id": "eval", "content": texts[inputs["file"]]}]}
        return {"profile": parse(state)["parsed_resumes"][0]}

    return target


def push_langsmith_live(pdf_dir: Path) -> None:
    """Experiment ที่เรียก AI จริง 9 ไฟล์ (2 call ต่อไฟล์ = 18 call) — มีเวลาและ token ในหน้า Experiment."""
    from langsmith import Client, evaluate

    from app.database import close_pool
    from app.utils.pdf_extractor import extract_text_from_pdf

    texts = {f: extract_text_from_pdf((pdf_dir / f).read_bytes()) for f in CASES}
    name = _dataset(Client())
    try:
        # ทีละไฟล์ — ไม่ยิง Gemini พร้อมกัน และเวลาที่วัดไม่เพี้ยนเพราะแย่งกัน
        evaluate(live_target(texts), data=name, evaluators=EVALUATORS,
                 experiment_prefix="resume-parser-live", max_concurrency=1)
    finally:
        close_pool()  # ตัวนับโควตาเขียน DB ทุก call
    print(f"\nอัปโหลด LangSmith แล้ว: dataset '{name}' + experiment 'resume-parser-live-…'")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", type=Path)
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--graph", action="store_true", help="รันทั้งกราฟ 3 คน (~12 call)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--replay", type=Path, help="คิดตัวเลขจากผลดิบที่เก็บไว้ ไม่เรียก AI")
    ap.add_argument("--price-in", type=float, help="USD ต่อ 1M token ขาเข้า")
    ap.add_argument("--price-out", type=float, help="USD ต่อ 1M token ขาออก")
    ap.add_argument("--langsmith", action="store_true")
    ap.add_argument("--langsmith-live", action="store_true",
                    help="เรียก AI จริง 18 call แล้วส่งผลพร้อมเวลา/token เข้า LangSmith (ใช้กับ --pdf-dir)")
    args = ap.parse_args(argv)

    if args.langsmith_live:
        if not args.pdf_dir:
            ap.error("--langsmith-live ต้องใส่ --pdf-dir")
        push_langsmith_live(args.pdf_dir)
        return 0

    if args.replay:
        raw = json.loads(args.replay.read_text(encoding="utf-8"))
    else:
        if not args.pdf_dir:
            ap.error("ต้องใส่ --pdf-dir (หรือ --replay)")
        from app.database import close_pool
        try:
            raw = collect(args.pdf_dir, args.rounds, args.graph)
        finally:
            close_pool()
        if args.out:
            args.out.write_text(json.dumps(raw, ensure_ascii=False, default=str), encoding="utf-8")
            print(f"เก็บผลดิบไว้ที่ {args.out}")
    summary = report(raw, args.price_in, args.price_out)
    if args.langsmith:
        push_langsmith(raw, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
