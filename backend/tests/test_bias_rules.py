"""ด่านกฎตายตัวของตัวตรวจอคติ — ไม่เรียก LLM

สองเรื่องที่ต้องไม่พัง: จับคำอคติที่ชัดได้ทุกหมวด และ **ไม่เตือนผิด** กับข้อความธรรมดา
เพราะคำเตือนที่ไม่จริงทำให้ HR เลิกเชื่อคำเตือนทั้งหมด
"""
import pytest

from app.agents.bias_rules import RuleHit, categories, find_biased_phrases, merge_criteria


def _phrases(text: str) -> list[str]:
    return [h.phrase for h in find_biased_phrases(text)]


@pytest.mark.parametrize(
    "text, category, phrase",
    [
        ("คุณสมบัติ: Python, เพศชาย อายุไม่เกิน 30 ปี", "เพศ", "เพศชาย"),
        ("รับเฉพาะผู้หญิง", "เพศ", "รับเฉพาะผู้หญิง"),
        ("Male only", "เพศ", "Male only"),
        ("คุณสมบัติ: Python, เพศชาย อายุไม่เกิน 30 ปี", "อายุ", "อายุไม่เกิน 30 ปี"),
        ("อายุ 22-35 ปี", "อายุ", "อายุ 22-35 ปี"),
        ("อายุ 25ปี ขึ้นไป", "อายุ", "อายุ 25ปี ขึ้นไป"),
        ("aged 25-35", "อายุ", "aged 25-35"),
        ("สถานภาพโสด", "สถานภาพสมรส", "สถานภาพโสด"),
        ("ยังไม่แต่งงาน ไม่มีบุตร", "สถานภาพสมรส", "ยังไม่แต่งงาน"),
        ("ไม่มีภาระครอบครัว", "สถานภาพสมรส", "ไม่มีภาระครอบครัว"),
        ("ส่วนสูง 160 ซม.ขึ้นไป", "รูปลักษณ์", "ส่วนสูง 160 ซม."),
        ("น้ำหนักไม่เกิน 55 กก.", "รูปลักษณ์", "น้ำหนักไม่เกิน 55 กก."),
        ("หน้าตาดี", "รูปลักษณ์", "หน้าตาดี"),
        ("ไม่มีความพิการ", "ความพิการ", "ไม่มีความพิการ"),
        ("อวัยวะครบ 32", "ความพิการ", "อวัยวะครบ 32"),
        ("able-bodied", "ความพิการ", "able-bodied"),
        ("สัญชาติไทยเท่านั้น", "เชื้อชาติ/สัญชาติ", "สัญชาติไทยเท่านั้น"),
        ("ภูมิลำเนาอยู่ในกรุงเทพ", "เชื้อชาติ/สัญชาติ", "ภูมิลำเนาอยู่ในกรุงเทพ"),
        ("นับถือศาสนาพุทธ", "ศาสนา", "นับถือศาสนาพุทธ"),
        ("จบจากมหาวิทยาลัยชั้นนำ", "สถาบันการศึกษา", "มหาวิทยาลัยชั้นนำ"),
        ("top university graduate", "สถาบันการศึกษา", "top university"),
    ],
)
def test_จับได้ทุกหมวด(text, category, phrase):
    assert RuleHit(category, phrase) in find_biased_phrases(text)


@pytest.mark.parametrize(
    "text",
    [
        "Build a Single Page Application",
        "บุคลิกภาพดี มีมนุษยสัมพันธ์",
        "ทำงานใกล้ชายฝั่ง",
        "มีอายุงาน 2 ปีขึ้นไป",
        "สัญชาติไทย",  # บางงานกฎหมายบังคับจริง
        "ไม่จำกัดเพศ อายุ เชื้อชาติ ศาสนา",  # ประโยคเปิดรับทุกคน
        "รับทั้งเพศชายและเพศหญิง",
        "เพศชายหรือเพศหญิง",
        "Native English speaker",
        "Average response time under 30 minutes",
        "",
    ],
)
def test_ไม่เตือนผิด(text):
    assert find_biased_phrases(text) == []


def test_ประกาศเต็มที่สะอาดไม่มีคำเตือน():
    jd = """Junior Web Developer
    ทักษะที่ต้องมี: HTML5, CSS3, JavaScript (ES6+), Responsive Design, Git, RESTful API, JSON
    ทักษะที่อยากได้: React.js หรือ Vue.js, Node.js, MySQL, npm, VS Code, Postman
    สวัสดิการ: ประกันสังคม, ทำงานแบบไฮบริด"""
    assert find_biased_phrases(jd) == []


def test_ปฏิเสธเพศไม่ลบล้างเกณฑ์อายุที่มีตัวเลข():
    # "ไม่จำกัดเพศ" ไม่ได้แปลว่าเรื่องอายุไม่กีดกัน
    assert _phrases("ไม่จำกัดเพศ อายุไม่เกิน 30 ปี") == ["อายุไม่เกิน 30 ปี"]


def test_phrase_เป็นข้อความจากประกาศจริงเสมอ():
    jd = "เพศชาย อายุ 22-35 ปี สถานภาพโสด ส่วนสูง 170 ซม. จบจากมหาวิทยาลัยชั้นนำ"
    hits = find_biased_phrases(jd)
    assert len(hits) == 5
    assert all(h.phrase in jd for h in hits)


def test_ช่วงที่ซ้อนกันเก็บอันยาวที่สุดครั้งเดียว():
    # "สถานภาพโสด" มีคำว่า "โสด" อยู่ข้างใน — ต้องไม่ได้สองรายการ
    assert _phrases("สถานภาพโสด") == ["สถานภาพโสด"]


def test_เรียงตามตำแหน่งและไม่ซ้ำ():
    assert _phrases("อายุไม่เกิน 30 ปี และเพศชาย … เพศชาย") == ["อายุไม่เกิน 30 ปี", "เพศชาย"]


def test_merge_ไม่ซ้ำกับที่_LLM_รวมไว้เป็นข้อเดียว():
    hits = [RuleHit("เพศ", "เพศชาย"), RuleHit("อายุ", "อายุไม่เกิน 30 ปี")]
    assert merge_criteria(["เพศชาย อายุไม่เกิน 30 ปี"], hits) == ["เพศชาย อายุไม่เกิน 30 ปี"]


def test_merge_ของ_LLM_สั้นกว่าก็ถือว่าเรื่องเดียวกัน():
    hits = [RuleHit("อายุ", "อายุไม่เกิน 30 ปี")]
    assert merge_criteria(["อายุไม่เกิน 30"], hits) == ["อายุไม่เกิน 30"]


def test_merge_เพิ่มของที่_LLM_พลาด():
    hits = [RuleHit("เพศ", "เพศชาย"), RuleHit("สถานภาพสมรส", "สถานภาพโสด")]
    assert merge_criteria(["เพศชาย"], hits) == ["เพศชาย", "สถานภาพโสด"]


def test_merge_ทิ้งค่าว่างของ_LLM():
    assert merge_criteria(["", "  "], []) == []


def test_categories_ไม่ซ้ำตามลำดับที่เจอ():
    hits = [RuleHit("เพศ", "a"), RuleHit("อายุ", "b"), RuleHit("เพศ", "c")]
    assert categories(hits) == ["เพศ", "อายุ"]


# ── build_jd_audit: รวมผล LLM กับกฎเป็นผลตรวจของตำแหน่ง ──

from app.agents.models import BiasAudit  # noqa: E402
from app.agents.nodes.bias_auditor import _MAX_JD_CHARS, build_jd_audit  # noqa: E402

_BIASED = "ตำแหน่ง Backend Developer\nคุณสมบัติ: Python, เพศชาย อายุไม่เกิน 30 ปี"
_PASSED = BiasAudit(is_biased=False, audit_status="passed", audit_log="ไม่พบการใช้ข้อมูลอคติ")


def test_audit_กฎเจอแต่_llm_ตอบผ่าน_ต้อง_flagged_และข้อความไม่ขัดกันเอง():
    a = build_jd_audit(_PASSED, _BIASED)
    assert a["status"] == "flagged" and a["llm_checked"] is True
    assert "ไม่พบ" not in a["log"]
    assert "เพศชาย" in a["log"] and "อายุไม่เกิน 30 ปี" in a["log"]


def test_audit_ไม่ซ้ำกับที่_llm_รายงานไว้แล้ว():
    llm = BiasAudit(
        is_biased=True, audit_status="flagged", audit_log="ประกาศระบุเพศและอายุ",
        biased_jd_criteria=["เพศชาย อายุไม่เกิน 30 ปี"],
    )
    a = build_jd_audit(llm, _BIASED)
    assert a["log"].startswith("ประกาศระบุเพศและอายุ")  # LLM flagged เอง ข้อความของมันถูกเก็บ
    warning = a["log"].splitlines()[-1]
    assert warning.count("เพศชาย") == 1 and warning.count("อายุไม่เกิน 30") == 1


def test_audit_กฎอ่านประกาศเต็มไม่ตัดตามเพดาน_token():
    jd = "ตำแหน่ง Backend Developer\n" + ("รายละเอียดงาน " * 600) + "\nสถานภาพโสด"
    assert len(jd) > _MAX_JD_CHARS
    assert "สถานภาพโสด" in build_jd_audit(_PASSED, jd)["log"]


def test_audit_ไม่มี_llm_ประกาศสะอาดผ่าน():
    a = build_jd_audit(None, "Python Developer\nPython, Docker")
    assert a["status"] == "passed" and a["llm_checked"] is False and a["jd_criteria"] == []


def test_audit_llm_ตอบผ่านประกาศสะอาดคงข้อความเดิม():
    a = build_jd_audit(_PASSED, "Python Developer\nPython, Docker")
    assert a["status"] == "passed" and a["log"] == "ไม่พบการใช้ข้อมูลอคติ"


def test_audit_เกณฑ์ทักษะที่มีอคติส่งต่อให้ลูป_revise():
    llm = BiasAudit(
        is_biased=True, audit_status="flagged", audit_log="x",
        biased_required_skills=[" มหาวิทยาลัยชั้นนำ ", ""],
    )
    assert build_jd_audit(llm, "Python")["biased_required_skills"] == ["มหาวิทยาลัยชั้นนำ"]
