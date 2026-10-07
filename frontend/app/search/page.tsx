"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import ScoreRing from "@/components/score-ring";
import { searchPeople } from "@/lib/api";
import { BANDS, initials, scoreBand } from "@/lib/types";
import type { PersonApplication, PersonSearchHit } from "@/lib/types";
import Spinner from "@/components/spinner";

const EXAMPLES = [
  "นักออกแบบกราฟิกและงานดีไซน์เว็บ",
  "วิศวกรหลังบ้านที่ทำฐานข้อมูลและ API",
  "คนที่เคยทำงานกับ LLM",
];

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<PersonSearchHit[] | null>(null);
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
      setHits(await searchPeople(query));
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
            {busy && <Spinner className="text-[18px]" />}
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
            <ResultRow key={h.applications[0]?.candidate_id ?? i} hit={h} />
          ))}
        </div>
      )}
    </div>
  );
}

/** ตำแหน่งที่โชว์ก่อนพับเป็น "+ อีก N ตำแหน่ง" */
const MAX_CHIPS = 4;

/** ใบสมัครของคนหนึ่งคน รวมตามชื่อตำแหน่ง — ตำแหน่งชื่อซ้ำ (สร้างซ้ำตอนทดสอบ) ขึ้นเป็นชิปเดียว ×N
 *  ตัวแทนของกลุ่ม = ใบที่คะแนนสูงสุด (เท่ากันเอาใบล่าสุด เพราะ apps เรียงล่าสุดก่อนแล้ว) */
interface TitleGroup {
  title: string;
  count: number;
  best: PersonApplication;
}

function groupByTitle(apps: PersonApplication[]): TitleGroup[] {
  const map = new Map<string, TitleGroup>();
  for (const a of apps) {
    const title = a.job_title ?? "—";
    const g = map.get(title);
    if (!g) {
      map.set(title, { title, count: 1, best: a });
    } else {
      g.count += 1;
      if ((a.fit_score ?? -1) > (g.best.fit_score ?? -1)) g.best = a;
    }
  }
  // คะแนนสูงก่อน — HR อยากเห็นตำแหน่งที่คนนี้เหมาะที่สุดก่อน
  return [...map.values()].sort((x, y) => (y.best.fit_score ?? -1) - (x.best.fit_score ?? -1));
}

/** หนึ่งแถว = หนึ่งคน (รวมใบสมัครจากไฟล์เดียวกันหรืออีเมลเดียวกันแล้ว)
 *  ใบเดียว: วงกลมคะแนน + "เคยสมัคร" · หลายใบ: วงกลมคะแนนสูงสุด + ชิปรายตำแหน่งพร้อมจุดสีแบนด์ */
function ResultRow({ hit }: { hit: PersonSearchHit }) {
  // distance เป็น cosine (0 = เหมือนกันสนิท) — แปลงเป็น "ความใกล้เคียง" ให้อ่านง่าย
  const similarity = Math.max(0, Math.min(100, Math.round((1 - hit.distance) * 100)));
  const apps = hit.applications;
  const single = apps.length === 1;
  const groups = useMemo(() => groupByTitle(apps), [apps]);
  const [expanded, setExpanded] = useState(false);
  const top = single ? apps[0] : groups[0].best;
  const shown = expanded ? groups : groups.slice(0, MAX_CHIPS);
  const hidden = groups.length - MAX_CHIPS;

  return (
    <div className="glass-card rounded-2xl px-md py-sm">
      <div className="flex items-center gap-md flex-wrap">
        <div className="w-12 h-12 flex-none rounded-xl flex items-center justify-center text-body-md font-semibold bg-primary-container text-on-primary-container">
          {initials(hit.full_name)}
        </div>

        <div className="flex-[2] min-w-[180px] space-y-0.5">
          <div className="text-body-md font-semibold text-on-surface">{hit.full_name}</div>
          <div className="text-label-md text-on-surface-variant">{hit.email ?? "—"}</div>
          <div className="flex items-center gap-xs flex-wrap text-label-sm text-outline">
            <span className="inline-flex items-center gap-1">
              <span className="material-symbols-outlined text-[16px]">description</span>
              {single ? (
                <>เคยสมัคร: {apps[0].job_title ?? "—"}</>
              ) : (
                <>
                  สมัคร {apps.length} ครั้ง · {groups.length} ตำแหน่ง
                </>
              )}
            </span>
            {hit.merged_by === "same_email" && (
              <span
                title="คนละไฟล์ แต่อีเมลในเรซูเม่ตรงกัน จึงรวมเป็นคนเดียวกัน"
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary-fixed text-on-primary-fixed-variant font-semibold"
              >
                <span className="material-symbols-outlined text-[14px]">link</span>
                รวม {hit.file_count} ไฟล์ · อีเมลตรงกัน
              </span>
            )}
          </div>
        </div>

        <div className="flex-none w-[88px] text-center" title="ความหมายของคำค้นใกล้กับเรซูเม่แค่ไหน">
          <div className="text-body-md font-semibold text-primary">{similarity}%</div>
          <div className="h-1 rounded-full bg-outline-variant/40 overflow-hidden my-1">
            <div className="h-full rounded-full bg-primary" style={{ width: `${similarity}%` }} />
          </div>
          <div className="text-label-sm text-outline">ความใกล้เคียง</div>
        </div>

        {single ? (
          <ScoreRing score={top.fit_score} />
        ) : (
          <div className="flex flex-col items-center gap-base min-w-[84px]">
            <ScoreRing score={top.fit_score} showLabel={false} />
            <div className="text-[10px] font-semibold text-outline">คะแนนสูงสุด</div>
          </div>
        )}

        <div className="flex-none">
          <Link
            href={`/jobs/${top.job_id}/candidates/${top.candidate_id}`}
            aria-label={`ดูรายละเอียดของ ${hit.full_name}`}
            className="btn-tonal"
          >
            ดูรายละเอียด
            <span className="material-symbols-outlined text-[18px]">chevron_right</span>
          </Link>
        </div>
      </div>

      {!single && (
        <div className="mt-sm pt-sm border-t border-outline-variant/40 flex flex-wrap items-center gap-xs md:pl-[64px]">
          {shown.map((g) => {
            const band = BANDS[scoreBand(g.best.fit_score)];
            return (
              <Link
                key={g.title}
                href={`/jobs/${g.best.job_id}/candidates/${g.best.candidate_id}`}
                title={g.count > 1 ? `สมัคร ${g.count} ครั้ง — เปิดใบที่คะแนนสูงสุด` : undefined}
                className="inline-flex items-center gap-1.5 text-[12px] font-semibold pl-2.5 pr-2 py-1 rounded-full bg-glass/60 border border-outline/30 text-on-surface-variant hover:bg-glass hover:text-on-surface transition-colors"
              >
                {g.title}
                {g.count > 1 && <span className="text-outline font-normal">×{g.count}</span>}
                <span className="inline-flex items-center gap-1 pl-1.5 ml-0.5 border-l border-outline/30">
                  <span className="w-2 h-2 rounded-full" style={{ background: band.color }} />
                  <span style={{ color: band.color }}>{g.best.fit_score ?? "–"}</span>
                </span>
              </Link>
            );
          })}
          {hidden > 0 && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="text-[12px] font-semibold px-2.5 py-1 rounded-full text-primary hover:bg-primary-fixed/60 transition-colors"
            >
              {expanded ? "ย่อ" : `+ อีก ${hidden} ตำแหน่ง`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
