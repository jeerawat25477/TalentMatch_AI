"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import Breadcrumb from "@/components/breadcrumb";
import { getInterviews } from "@/lib/api";
import { INTERVIEW_RESULT } from "@/lib/types";
import type { InterviewSlot } from "@/lib/types";
import Spinner from "@/components/spinner";

/**
 * ตารางนัดสัมภาษณ์รวมทุกตำแหน่ง — อ่านอย่างเดียว
 *
 * วันนัดยังแก้ที่กระดานของแต่ละตำแหน่งเหมือนเดิม หน้านี้ตอบคำถามเดียวคือ "ช่วงนี้ต้อง
 * สัมภาษณ์ใครบ้าง" ซึ่งเดิมต้องเปิดการ์ดทีละใบถึงจะรู้
 *
 * เป็นรายการจัดกลุ่มตามวัน ไม่ใช่ตารางเดือนแบบ grid: จำนวนนัดจริงต่อสัปดาห์มีไม่กี่รายการ
 * รายการตอบได้เท่ากันโดยไม่ต้องมีปฏิทินให้ดูแล และขยายเป็นมุมมองเดือนทีหลังได้บน
 * endpoint เดิม
 */

// ช่วงเวลาให้เลือก — คำนวณฝั่งนี้แล้วส่ง ISO พร้อมโซนเวลาไป backend ไม่เดาโซนให้
const RANGES = [
  { key: "next7", label: "7 วันข้างหน้า", from: 0, to: 7 },
  { key: "next30", label: "30 วันข้างหน้า", from: 0, to: 30 },
  { key: "past7", label: "ย้อนหลัง 7 วัน", from: -7, to: 0 },
] as const;

type RangeKey = (typeof RANGES)[number]["key"];

/** เที่ยงคืนของวันนี้บวกจำนวนวัน — ขอบเขตจึงเป็น "ทั้งวัน" เสมอ ไม่ใช่นับจากเวลาปัจจุบัน */
function dayBoundary(offsetDays: number): Date {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() + offsetDays);
  return d;
}

/** หัวกลุ่มของวันนั้น — "วันนี้"/"พรุ่งนี้" อ่านง่ายกว่าวันที่เต็มสำหรับสองวันที่ใช้บ่อยที่สุด */
function dayLabel(d: Date): string {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((d.getTime() - today.getTime()) / 86400000);
  const full = d.toLocaleDateString("th-TH", {
    weekday: "long",
    day: "numeric",
    month: "short",
  });
  if (diff === 0) return `วันนี้ · ${full}`;
  if (diff === 1) return `พรุ่งนี้ · ${full}`;
  if (diff === -1) return `เมื่อวาน · ${full}`;
  return full;
}

function groupByDay(slots: InterviewSlot[]): { key: string; label: string; slots: InterviewSlot[] }[] {
  const groups: { key: string; label: string; slots: InterviewSlot[] }[] = [];
  for (const s of slots) {
    const at = new Date(s.scheduled_at);
    if (Number.isNaN(at.getTime())) continue; // ค่าผิดรูป: ข้าม ดีกว่าทำทั้งหน้าพัง
    const midnight = new Date(at);
    midnight.setHours(0, 0, 0, 0);
    const key = midnight.toISOString();
    const last = groups[groups.length - 1];
    // backend เรียงมาแล้ว วันเดียวกันจึงติดกันเสมอ ไม่ต้องทำ map ให้เสียลำดับ
    if (last && last.key === key) last.slots.push(s);
    else groups.push({ key, label: dayLabel(midnight), slots: [s] });
  }
  return groups;
}

export default function InterviewsPage() {
  const [range, setRange] = useState<RangeKey>("next7");
  const picked = RANGES.find((r) => r.key === range) ?? RANGES[0];

  // คีย์ SWR ผูกกับช่วงที่เลือก — เปลี่ยนช่วงแล้วดึงใหม่เอง
  const { data, error, isLoading } = useSWR<InterviewSlot[]>(
    ["interviews", picked.key],
    () =>
      getInterviews(
        dayBoundary(picked.from).toISOString(),
        dayBoundary(picked.to + 1).toISOString(),
      ),
    { refreshInterval: 60000 },
  );

  const groups = useMemo(() => groupByDay(data ?? []), [data]);
  const overdue = (data ?? []).filter((s) => s.overdue).length;

  return (
    <div className="space-y-md">
      <Breadcrumb items={[{ label: "ตารางสัมภาษณ์" }]} />

      <div className="flex items-end justify-between gap-sm flex-wrap">
        <div>
          <h1 className="text-headline-lg text-on-surface">ตารางสัมภาษณ์</h1>
          <p className="text-label-sm text-on-surface-variant">
            นัดของทุกตำแหน่งรวมกัน — วันนัดแก้ได้ที่กระดานของแต่ละตำแหน่ง
          </p>
        </div>
        <div className="flex gap-base bg-glass/50 border border-outline/30 backdrop-blur-md p-1 rounded-xl">
          {RANGES.map((r) => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              className={`px-sm py-1.5 rounded-lg text-label-md font-semibold transition-colors ${
                range === r.key
                  ? "bg-primary text-on-primary"
                  : "text-on-surface-variant hover:bg-glass/40"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {overdue > 0 && (
        <div
          role="note"
          className="glass-card rounded-2xl p-sm flex items-start gap-xs border border-tertiary/40"
        >
          <span
            className="material-symbols-outlined text-tertiary text-[20px] flex-none"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            pending_actions
          </span>
          <p className="text-label-md text-on-surface">
            มี {overdue} นัดที่เลยเวลามาแล้วแต่ยังไม่ได้บันทึกผลสัมภาษณ์
          </p>
        </div>
      )}

      {error && (
        <p className="text-error text-label-md" role="alert">
          โหลดตารางไม่สำเร็จ ลองรีเฟรชหน้าอีกครั้ง
        </p>
      )}

      {isLoading && !data && <p className="text-outline text-label-md flex items-center gap-xs" role="status">
          <Spinner className="text-[18px]" />
          กำลังโหลด…
        </p>}

      {data && groups.length === 0 && !error && (
        <div className="glass-card rounded-2xl p-lg text-center">
          <p className="text-label-md text-on-surface">ยังไม่มีนัดสัมภาษณ์ในช่วงนี้</p>
          <p className="text-label-sm text-on-surface-variant mt-1">
            วันนัดกรอกได้จากกระดานของแต่ละตำแหน่ง — ถ้ายังไม่กรอก นัดนั้นจะไม่ขึ้นที่นี่
          </p>
        </div>
      )}

      {groups.map((g) => (
        <section key={g.key} className="glass-card rounded-2xl p-md">
          <h2 className="text-label-md font-semibold text-on-surface mb-xs">
            {g.label}
            <span className="ms-xs text-label-sm font-normal text-on-surface-variant">
              {g.slots.length} นัด
            </span>
          </h2>
          <ul className="space-y-xs">
            {g.slots.map((s) => (
              <li key={`${s.candidate_id}-${s.scheduled_at}`}>
                <Link
                  href={`/jobs/${s.job_id}/candidates/${s.candidate_id}`}
                  className="flex items-center gap-sm p-sm rounded-lg bg-glass/30 hover:bg-glass/60 transition-colors"
                >
                  <span className="w-[54px] flex-none text-label-md font-semibold text-on-surface">
                    {new Date(s.scheduled_at).toLocaleTimeString("th-TH", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-label-md text-on-surface truncate">
                      {s.full_name}
                    </span>
                    <span className="block text-label-sm text-outline truncate">
                      {s.job_title}
                      {s.location && ` · ${s.location}`}
                    </span>
                  </span>
                  {s.interview_result && (
                    <span
                      className={`flex-none inline-flex items-center gap-1 text-label-sm font-semibold px-2.5 py-1 rounded-full ${
                        INTERVIEW_RESULT[s.interview_result].chip
                      }`}
                    >
                      <span className="material-symbols-outlined text-[15px]">
                        {INTERVIEW_RESULT[s.interview_result].icon}
                      </span>
                      {INTERVIEW_RESULT[s.interview_result].label}
                    </span>
                  )}
                  {s.overdue && (
                    <span className="flex-none text-label-sm font-semibold px-2.5 py-1 rounded-full bg-tertiary-container/40 text-on-tertiary-container">
                      ยังไม่บันทึกผล
                    </span>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
