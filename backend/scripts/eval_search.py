"""วัดคุณภาพหน้า "ค้นหาผู้สมัคร" — ชุดคำค้นพร้อมคนที่ควรเจอ แล้วคิด Hit@1 / Hit@3 / MRR.

ใช้โค้ดเดียวกับหน้าเว็บจริง (vectors.search_vector → candidates.people_from_hits) ผลจึงเป็นสิ่งที่ HR เห็น
รันทุกครั้งที่แก้วิธีค้น (ข้อความที่ embed, การจัดอันดับ, การรวมคน) แล้วเทียบกับผลฐานใน
memory-bank/06_scoring_criteria.md

ไม่เขียน DB · ไม่ใช้ chat quota · ใช้ embedding 1 ครั้งต่อคำค้นที่ยังไม่อยู่ในแคช

    # รอบแรก (15 embedding) แล้วเก็บเวกเตอร์คำค้นไว้
    docker compose exec backend python scripts/eval_search.py --cache /tmp/search_q.json
    # รอบต่อไป ไม่เรียก embedding เลย (ถ้าคำค้นไม่เปลี่ยน)
    docker compose exec backend python scripts/eval_search.py --cache /tmp/search_q.json

⚠ คำตอบที่ถูกตั้งจากผู้สมัครในฐานข้อมูล dev ตอน 2026-10-07 (13 คน) ระบุด้วยอีเมล
  ปรับ 2026-10-12 หลังลบข้อมูลทดสอบซ้ำ: Kittipat หายจากระบบ (เหลือ 12 คน) — เอาออกจากคำตอบ
ฐานข้อมูลเปลี่ยน (เพิ่ม/ลบคน) ต้องทบทวน CASES ก่อนเชื่อตัวเลข
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# (คำค้น, แบบ, อีเมลของคนที่ควรเจอ) — set ว่าง = ไม่มีคนที่ตรงในระบบ (วัดว่า % สูงแค่ไหนตอนไม่มีใครตรง)
ANAN = "anan@example.com"
NATTIDA = "nattida.s@example.com"
WORAMET = "woramet.b@example.com"
JEERAWAT = "jeerawat.sakwong@gmail.com"
SOMCHAI = "somchai@example.com"
SUDA = "suda@example.com"
SUREERAT = "66010914021@msu.ac.th"
CHYANEE = "chyaneerungnpakan@gmail.com"
PHAKPHOOM = "manpakphoom@gmail.com"
PRIYANON = "priyanon.kn@gmail.com"
WATCHARAPHON = "watcharaphonn8@gmail.com"

CASES: list[tuple[str, str, set[str]]] = [
    ("อยากได้คนออกแบบกราฟิก", "พูด", {ANAN}),
    ("Photoshop, Illustrator, Figma", "คีย์เวิร์ด", {ANAN}),
    ("คนที่ยิงแอดเฟซบุ๊กเป็น", "พูด", {NATTIDA}),
    ("Facebook Ads, Google Analytics", "คีย์เวิร์ด", {NATTIDA}),
    ("คนที่เคยทำงานขาย อยากย้ายมาทำการตลาด", "พูด", {WORAMET}),
    ("นักการตลาดออนไลน์", "พูด", {NATTIDA, WORAMET}),
    ("โปรแกรมเมอร์หลังบ้านที่อยากเปลี่ยนสายไปทำ AI", "พูด", {JEERAWAT}),
    ("คนที่เคยทำงานกับ LLM", "พูด", {JEERAWAT, SOMCHAI}),
    ("Python, FastAPI", "คีย์เวิร์ด", {SOMCHAI, SUDA, JEERAWAT}),
    ("Docker, Kubernetes, AWS", "คีย์เวิร์ด", {SOMCHAI, SUDA, JEERAWAT}),  # ทั้งสามมี Docker
    ("นักศึกษาจบใหม่ ทำเว็บด้วย PHP กับ MySQL", "พูด",
     {SUREERAT, CHYANEE, PHAKPHOOM, PRIYANON, WATCHARAPHON, JEERAWAT}),
    ("Backend developer with years of experience", "อังกฤษ", {SOMCHAI, SUDA}),
    ("คนที่ทำ IoT กับ Arduino ได้", "พูด", {PHAKPHOOM, SUREERAT, CHYANEE, PRIYANON}),
    ("นักบัญชี ปิดงบการเงินได้", "ไม่มีในระบบ", set()),
    ("พยาบาล ดูแลผู้ป่วย", "ไม่มีในระบบ", set()),
]


# ระยะห่างขั้นต่ำ (หน่วย %) ระหว่าง "คนที่ใช่ที่ % ต่ำสุด" กับ "% สูงสุดตอนไม่มีใครตรง" ก่อนจะยอมตั้งเกณฑ์ "ไม่พบ"
MIN_SEPARATION = 5


def first_relevant_rank(people_emails: list[set[str]], relevant: set[str]) -> int | None:
    """อันดับ (เริ่ม 1) ของคนแรกที่ใช่ — แต่ละคนมีได้หลายอีเมล นับว่าใช่ถ้ามีอีเมลไหนตรง."""
    for i, emails in enumerate(people_emails, start=1):
        if emails & relevant:
            return i
    return None


def summarize(ranks: list[int | None]) -> dict:
    """Hit@1, Hit@3, MRR จากอันดับของคำค้นที่มีคำตอบ (None = ไม่เจอใน 10 อันดับ)."""
    n = len(ranks)
    if not n:
        return {"n": 0, "hit1": 0.0, "hit3": 0.0, "mrr": 0.0}
    return {
        "n": n,
        "hit1": sum(1 for r in ranks if r == 1) / n,
        "hit3": sum(1 for r in ranks if r is not None and r <= 3) / n,
        "mrr": sum(1 / r for r in ranks if r) / n,
    }


def _pct(distance: float) -> int:
    return round((1 - distance) * 100)


def main(argv: list[str]) -> int:
    from app.database import close_pool
    from app.routers.candidates import PEOPLE_SEARCH_FILES, people_from_hits
    from app.vectors import embed, search_vector

    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", help="ไฟล์เก็บเวกเตอร์คำค้น (json) — รันซ้ำไม่ต้อง embed ใหม่")
    args = ap.parse_args(argv)

    cache: dict[str, list[float]] = {}
    if args.cache and Path(args.cache).exists():
        cache = json.loads(Path(args.cache).read_text(encoding="utf-8"))
    embedded = 0

    by_kind: dict[str, list[int | None]] = {}
    neg_top: list[int] = []
    pos_rel: list[int] = []
    try:
        for query, kind, relevant in CASES:
            if query not in cache:
                cache[query] = embed(query)
                embedded += 1
            people = people_from_hits(search_vector(cache[query], limit=PEOPLE_SEARCH_FILES))[:10]
            emails = [set(p.get("emails") or []) for p in people]
            top = people[0] if people else None
            print(f"\n[{kind}] {query}")
            for i, p in enumerate(people[:3], start=1):
                mark = "✓" if emails[i - 1] & relevant else " "
                print(f"   {i}. {mark} {_pct(p['distance']):>3}%  {p['full_name']}")
            if not relevant:
                if top:
                    neg_top.append(_pct(top["distance"]))
                    print(f"   → ไม่มีคนที่ตรง · % สูงสุดที่ได้ {neg_top[-1]}%")
                continue
            rank = first_relevant_rank(emails, relevant)
            by_kind.setdefault(kind, []).append(rank)
            if rank:
                pos_rel.append(_pct(people[rank - 1]["distance"]))
            print(f"   → คนที่ใช่คนแรกอยู่อันดับ {rank if rank else 'ไม่ติด 10 อันดับ'}")
    finally:
        close_pool()

    if args.cache:
        Path(args.cache).write_text(json.dumps(cache), encoding="utf-8")

    print("\n" + "=" * 60)
    all_ranks = [r for rs in by_kind.values() for r in rs]
    for label, ranks in [("รวม", all_ranks)] + sorted(by_kind.items()):
        s = summarize(ranks)
        print(f"{label:<12} n={s['n']:<3} Hit@1 {s['hit1']:.0%}  Hit@3 {s['hit3']:.0%}  MRR {s['mrr']:.2f}")
    if neg_top and pos_rel:
        print(f"\nคำค้นที่ไม่มีใครตรง: % สูงสุด {max(neg_top)}% · "
              f"คนที่ใช่ (อันดับแรกที่เจอ): ต่ำสุด {min(pos_rel)}% สูงสุด {max(pos_rel)}%")
        gap = min(pos_rel) - max(neg_top)
        # ห่างแค่ไม่กี่ % คือบังเอิญได้ — ข้อมูลเพิ่มนิดเดียวก็ทับกัน จึงยังไม่นับว่าตั้งเกณฑ์ได้
        if gap >= MIN_SEPARATION:
            verdict = f"ห่างกัน {gap}% — พอลองตั้งเกณฑ์ 'ไม่พบ' ได้"
        elif gap > 0:
            verdict = f"ห่างกันแค่ {gap}% — น้อยเกินจะตั้งเกณฑ์ 'ไม่พบ'"
        else:
            verdict = "ทับกัน — ตั้งเกณฑ์ 'ไม่พบ' ไม่ได้"
        print(f"→ {verdict}")
    print(f"\nembedding ที่เรียกรอบนี้: {embedded} ครั้ง")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
