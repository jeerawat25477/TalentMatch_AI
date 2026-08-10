"""Retrieval agent (RAG) — ดึงผู้สมัครเก่าที่โปรไฟล์คล้ายกันจากคลังเวกเตอร์.

วางระหว่าง resume_parser → matcher · เป็น feature เสริม เปิด/ปิดด้วย env RAG_ENABLED
- ปิด (ดีฟอลต์เมื่อไม่ตั้ง) → no-op คืน similar ว่าง กราฟรันเหมือนไม่มีโหนดนี้
- เปิด → ค้นด้วยทักษะที่ parser แกะได้ แล้วแนบผลเข้า state ให้ planner/หน้าเว็บใช้

ใช้แค่ embedding quota (แยกจาก chat 20/วัน) และห่อ try/except — retrieval ล้มต้องไม่ทำให้กราฟพัง
"""
import logging
import os

from app.agents.state import HRSystemState
from app.vectors import search

log = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.getenv("RAG_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def retrieve_similar(state: HRSystemState) -> dict:
    profile = state["parsed_resumes"][0]
    cid = profile["candidate_id"]

    if not _enabled():
        return {"similar_candidates": {cid: []}}

    # query จากทักษะที่แกะได้ — สั้นและตรงประเด็นกว่าใช้ resume ดิบทั้งก้อน
    skills = profile.get("skills") or []
    query = ", ".join(str(s) for s in skills).strip()
    if not query:
        return {"similar_candidates": {cid: []}}

    top_k = int(os.getenv("RAG_TOP_K", "3"))
    try:
        hits = search(query, limit=top_k, exclude_candidate_id=cid)
    except Exception as exc:  # noqa: BLE001 — feature เสริม ห้ามทำให้กราฟล้ม
        log.warning("retrieval agent หาผู้สมัครคล้าย %s ไม่สำเร็จ: %s", cid, exc)
        return {"similar_candidates": {cid: []}}

    # เก็บเฉพาะฟิลด์ที่ใช้จริง (planner + หน้าเว็บ) และแปลง UUID/ค่าเป็น JSON-safe
    slim = [
        {
            "id": str(h["id"]),
            "full_name": h.get("full_name"),
            "job_title": h.get("job_title"),
            "fit_score": h.get("fit_score"),
            "distance": round(float(h["distance"]), 4) if h.get("distance") is not None else None,
        }
        for h in hits
    ]
    log.info("retrieval agent: ผู้สมัคร %s เจอคนคล้าย %d คน", cid, len(slim))
    return {"similar_candidates": {cid: slim}}
