"""bias_ack.biased_skills — ทักษะในเกณฑ์คะแนนที่ตรงกับอคติ (ไม่ใช้ AI).

กฎต้องเข้มเรื่องเตือนผิด: ทักษะจริงอย่าง "English", "ภาษาอังกฤษ" ห้ามโดนจับ
แม้จะอยู่ในถ้อยคำที่ถูกเตือนก็ตาม — เช็คกับเกณฑ์ของตำแหน่งจริงทั้ง 16 ตำแหน่งแล้ว (0 จาก 199 ทักษะ)
"""
from app.bias_ack import biased_skill_message, biased_skills

PHRASE = "เป็นเจ้าของภาษาอังกฤษ (Native English speaker)"


def names(found):
    return [f["skill"] for f in found]


def test_matches_parenthetical_english_part():
    found = biased_skills(["Native English speaker"], [], [PHRASE], [])
    assert found == [{"skill": "Native English speaker", "side": "required", "phrase": PHRASE}]


def test_matches_thai_part_and_whole_phrase():
    assert names(biased_skills(["เป็นเจ้าของภาษาอังกฤษ", PHRASE], [], [PHRASE], [])) == [
        "เป็นเจ้าของภาษาอังกฤษ", PHRASE,
    ]


def test_real_skills_inside_a_flagged_phrase_are_not_caught():
    # ภาษาไทยไม่เว้นวรรค — "ภาษาอังกฤษ" อยู่ใน "เป็นเจ้าของภาษาอังกฤษ" แต่สั้นกว่า 60% ของถ้อยคำ
    assert biased_skills(["English", "ภาษาอังกฤษ", "Python", "Facebook Ads"], [], [PHRASE], []) == []


def test_skill_itself_matching_rules_without_phrase_must_be_removed():
    found = biased_skills([], ["อายุ 25-35 ปี"], [], [])
    assert found == [{"skill": "อายุ 25-35 ปี", "side": "preferred", "phrase": None}]


def test_group_with_one_biased_option():
    assert names(biased_skills(["Python | เพศชาย"], [], [], [])) == ["Python | เพศชาย"]


def test_acknowledged_phrase_is_allowed():
    assert biased_skills(["Native English speaker"], [], [PHRASE], [{"phrase": PHRASE}]) == []


def test_ack_does_not_cover_a_different_phrase():
    found = biased_skills(["เพศหญิง"], [], [PHRASE, "เพศหญิง"], [{"phrase": PHRASE}])
    assert names(found) == ["เพศหญิง"]


def test_message_tells_what_to_do():
    ackable = biased_skill_message([{"skill": "X", "side": "required", "phrase": "p"}])
    assert "จำเป็นกับงานนี้" in ackable
    remove_only = biased_skill_message([{"skill": "X", "side": "required", "phrase": None}])
    assert "ลบออก" in remove_only and "จำเป็นกับงานนี้" not in remove_only


# ---------- ถอนการยืนยัน + ป้าย "นับเป็นทักษะในคะแนน" ----------
from app.bias_ack import bias_view, scored_phrases, withdraw_blocked  # noqa: E402

ACK = {"phrase": PHRASE, "reason": "ประสานงานต่างประเทศทุกวัน", "by": "a", "at": "2026-10-07T00:00:00+00:00"}


def test_scored_phrases_only_when_skill_in_criteria():
    assert scored_phrases(["Native English speaker"], [], [PHRASE, "เพศหญิง"]) == {PHRASE}
    assert scored_phrases(["English"], [], [PHRASE]) == set()


def test_withdraw_blocked_while_skill_still_scored():
    blocked = withdraw_blocked(["Native English speaker"], [], [PHRASE], [ACK], [])
    assert [b["skill"] for b in blocked] == ["Native English speaker"]


def test_withdraw_allowed_after_skill_removed():
    assert withdraw_blocked(["Python"], [], [PHRASE], [ACK], []) == []


def test_preexisting_problem_does_not_block_other_acks():
    # ตำแหน่งเก่ามีทักษะอคติค้างอยู่ก่อนแล้ว — ยืนยันถ้อยคำอื่นต้องยังทำได้ (ไม่ใช่สิ่งที่การถอนครั้งนี้ทำ)
    other = {"phrase": "เพศหญิง", "reason": "ตรวจค้นผู้โดยสารหญิง", "by": "a", "at": ACK["at"]}
    assert withdraw_blocked(["Native English speaker"], [], [PHRASE, "เพศหญิง"], [], [other]) == []


def test_view_marks_scored_ack():
    view = bias_view({"jd_criteria": [PHRASE, "เพศหญิง"]}, [ACK],
                     {"required_skills": ["Native English speaker"], "preferred_skills": []})
    assert view["acknowledged"][0]["scored"] is True
    assert view["pending"] == ["เพศหญิง"]


def test_view_without_criteria_marks_nothing():
    view = bias_view({"jd_criteria": [PHRASE]}, [ACK])
    assert view["acknowledged"][0]["scored"] is False


def test_strip_skills_removes_matching_skill_and_group_option():
    from app.bias_ack import strip_skills

    out = strip_skills(["Python", "Native English speaker", "Thai | Native English speaker"],
                       ["Canva"], [PHRASE])
    assert out == {"required_skills": ["Python", "Thai"], "preferred_skills": ["Canva"]}
