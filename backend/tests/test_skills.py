"""เทสการเทียบทักษะ — เคสส่วนใหญ่มาจากข้อมูลจริงใน DB ที่ทำให้บั๊กเดิมโผล่.

รัน: docker compose exec backend python -m pytest tests/test_skills.py -v
"""
import pytest

from app.agents.skills import canonical, is_skill, matches, split_matched

# ทักษะจริงของผู้สมัครในระบบ (SELECT DISTINCT jsonb_array_elements_text(parsed_resume->'skills'))
REAL_OWNED = {
    "CSS", "Docker", "FastAPI", "Figma", "HTML", "LangGraph",
    "MongoDB", "Photoshop", "PostgreSQL", "Python", "Redis",
}


class TestRegressionSubstringBug:
    """บั๊กเดิม: `n in o or o in n` ทำให้ตัวอักษรสั้น ๆ ไป match กลางคำ."""

    @pytest.mark.parametrize(
        "required",
        ["R", "ML", "DL", "Java", "Go", "C"],
    )
    def test_short_skill_does_not_match_mid_word(self, required):
        # เดิม: R -> postgresql/docker/langgraph/redis, ML -> html
        assert matches(required, REAL_OWNED) is False

    def test_java_is_not_javascript(self):
        assert matches("Java", {"JavaScript"}) is False
        assert matches("JavaScript", {"Java"}) is False

    def test_r_is_not_react(self):
        assert matches("R", {"React"}) is False


class TestImplication:
    """ทักษะที่ครอบคลุมอีกทักษะโดยปริยาย — เดิม substring จับถูกโดยบังเอิญ."""

    def test_postgresql_implies_sql(self):
        assert matches("SQL", REAL_OWNED) is True

    def test_fastapi_implies_python_and_api(self):
        assert matches("Python", {"FastAPI"}) is True
        assert matches("REST API", {"FastAPI"}) is True

    def test_implication_is_one_way(self):
        # รู้ SQL ไม่ได้แปลว่าใช้ PostgreSQL เป็น
        assert matches("PostgreSQL", {"SQL"}) is False


class TestAliases:
    def test_spelling_variants(self):
        assert matches("Node.js", {"NodeJs"}) is True
        assert matches("PostgreSQL", {"Postgres"}) is True
        assert matches("Go", {"Golang"}) is True
        assert matches("Kubernetes", {"k8s"}) is True
        assert matches("Power BI", {"PowerBI"}) is True

    def test_canonical_is_stable(self):
        assert canonical("Node.js") == canonical("NodeJs") == "node js"
        assert canonical("  POSTGRES  ") == "postgresql"


class TestTokenBoundary:
    def test_required_subset_of_owned_matches(self):
        assert matches("SQL", {"SQL Server"}) is True
        assert matches("Testing", {"Unit Testing"}) is True
        assert matches("API", {"REST API"}) is True

    def test_owned_less_specific_does_not_match(self):
        # รู้ React ไม่ได้แปลว่าทำ React Native เป็น — ห้ามเทียบสองทาง
        assert matches("React Native", {"React"}) is False

    def test_case_and_whitespace_insensitive(self):
        assert matches("  docker ", {"DOCKER"}) is True


class TestIsSkill:
    @pytest.mark.parametrize(
        "role",
        ["data scientists", "engineers", "product owners", "solution architects",
         "software developers", "stakeholders"],
    )
    def test_role_nouns_are_not_skills(self, role):
        assert is_skill(role) is False

    @pytest.mark.parametrize(
        "skill",
        ["Python", "Power BI", "logging", "monitoring", "performance tuning",
         "Star Schema", "Prompt Engineering"],
    )
    def test_real_skills_pass(self, skill):
        assert is_skill(skill) is True

    def test_role_word_as_modifier_is_kept(self):
        # คำบทบาทที่เป็นคำขยาย ไม่ใช่คำหลัก ต้องไม่ถูกตัด
        assert is_skill("developer tools") is True


class TestSplitMatched:
    def test_filters_non_skills_out_of_denominator(self):
        required = ["Python", "PostgreSQL", "data scientists", "product owners"]
        hit, miss = split_matched(required, REAL_OWNED)
        assert hit == ["Python", "PostgreSQL"]
        assert miss == []
        # ตัวหารต้องเป็น 2 ไม่ใช่ 4 — ไม่งั้นคะแนนโดนกดเหลือครึ่ง
        assert len(hit) + len(miss) == 2

    def test_preserves_original_spelling(self):
        # gap_analysis ถูกส่งต่อให้ LLM เขียนเป็นภาษาคนและแสดงบน radar chart
        hit, _ = split_matched(["Postgres"], REAL_OWNED)
        assert hit == ["Postgres"]
