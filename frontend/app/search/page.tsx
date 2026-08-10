"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import ScoreRing from "@/components/score-ring";
import { searchCandidates } from "@/lib/api";
import { initials } from "@/lib/types";
import type { CandidateSearchHit } from "@/lib/types";

const EXAMPLES = [
  "นักออกแบบกราฟิกและงานดีไซน์เว็บ",
  "วิศวกรหลังบ้านที่ทำฐานข้อมูลและ API",
  "คนที่เคยทำงานกับ LLM",
];

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<CandidateSearchHit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(query: string) {
    if (!query.trim()) return;
    setQ(query);
    setBusy(true);
    setError(null);
    // เก็บคำค้นไว้บน URL เพื่อให้ refresh/แชร์ลิงก์แล้วได้ผลเดิม
    window.history.replaceState(null, "", `/search?q=${encodeURIComponent(query)}`);
    try {
      setHits(await searchCandidates(query));
    } catch (e) {
      setError(e instanceof Error ? e.message : "ค้นหาไม่สำเร็จ");
      setHits(null);
    } finally {
      setBusy(false);
    }
  }

  // เปิดหน้าด้วย /search?q=... แล้วค้นให้เลย (อ่านจาก window แทน useSearchParams
  // เพื่อเลี่ยงการต้องครอบ Suspense ตามข้อกำหนดของ App Router)
  useEffect(() => {
    const initial = new URLSearchParams(window.location.search).get("q");
    if (initial) run(initial);
    // ตั้งใจให้รันครั้งเดียวตอน mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-md">
      <header>
        <h1 className="text-headline-lg text-on-surface">ค้นหาผู้สมัคร</h1>
        <p className="text-label-md text-on-surface-variant mt-1">
          ค้นด้วยความหมาย ไม่ใช่การจับคำ — พิมพ์บรรยายคนที่ต้องการเป็นภาษาพูดได้เลย
        </p>
      </header>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(q);
        }}
        className="glass-card rounded-2xl p-md space-y-sm"
      >
        <div className="flex gap-sm">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="เช่น คนที่ถนัดงานข้อมูลและทำ dashboard ได้"
            className="input-glass flex-1"
            aria-label="คำค้นหา"
          />
          <button type="submit" disabled={busy || !q.trim()} className="btn-primary">
            <span className="material-symbols-outlined text-[18px]">search</span>
            {busy ? "กำลังค้น…" : "ค้นหา"}
          </button>
        </div>

        <div className="flex gap-base flex-wrap items-center">
          <span className="text-label-sm text-outline">ลองดู:</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => run(ex)}
              className="text-label-sm px-2.5 py-1 rounded-full bg-glass/40 text-on-surface-variant hover:text-primary hover:bg-primary/10 transition-colors"
            >
              {ex}
            </button>
          ))}
        </div>
      </form>

      {error && (
        <p className="text-error text-label-md" role="alert">
          {error}
        </p>
      )}

      {hits && hits.length === 0 && (
        <p className="text-outline text-label-md">
          ไม่พบผู้สมัคร — คลังเวกเตอร์อาจยังว่าง ลองอัปโหลด resume ก่อน
        </p>
      )}

      {hits && hits.length > 0 && (
        <div className="space-y-sm">
          {hits.map((h, i) => (
            <ResultRow key={h.id} hit={h} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}

const AVATAR_COLORS = ["#0058be", "#2170e4", "#006c49", "#825100", "#427e9e", "#5a4fcf"];

function ResultRow({ hit, index }: { hit: CandidateSearchHit; index: number }) {
  // distance เป็น cosine (0 = เหมือนกันสนิท) — แปลงเป็น "ความใกล้เคียง" ให้อ่านง่าย
  const similarity = Math.round((1 - hit.distance) * 100);

  return (
    <div className="glass-card rounded-2xl px-md py-sm flex items-center gap-md flex-wrap">
      <div
        className="w-12 h-12 flex-none rounded-xl flex items-center justify-center text-body-md font-semibold text-white"
        style={{ background: AVATAR_COLORS[index % AVATAR_COLORS.length] }}
      >
        {initials(hit.full_name)}
      </div>

      <div className="flex-[2] min-w-[180px]">
        <div className="text-body-md font-semibold text-on-surface mb-0.5">
          {hit.full_name}
        </div>
        <div className="text-label-md text-on-surface-variant">
          {hit.email ?? "—"}
        </div>
        {hit.job_title && (
          <div className="text-label-sm text-outline mt-0.5">
            เคยสมัคร: {hit.job_title}
          </div>
        )}
      </div>

      <div className="flex-none text-center">
        <div className="text-body-md font-semibold text-primary">{similarity}%</div>
        <div className="text-label-sm text-outline">ความใกล้เคียง</div>
      </div>

      <ScoreRing score={hit.fit_score} />

      {hit.job_id && (
        <div className="flex-none">
          <Link
            href={`/jobs/${hit.job_id}/candidates/${hit.id}`}
            aria-label={`ดูรายละเอียดของ ${hit.full_name}`}
            className="btn-tonal"
          >
            ดูรายละเอียด
            <span className="material-symbols-outlined text-[18px]">chevron_right</span>
          </Link>
        </div>
      )}
    </div>
  );
}
