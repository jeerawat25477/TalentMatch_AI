"use client";

import Link from "next/link";
import ScoreRing from "@/components/score-ring";
import { CONFIDENCE } from "@/lib/types";
import type { BoardItem, BoardStage } from "@/lib/types";

/** ป้ายของแต่ละคอลัมน์ — ใช้ร่วมกันทั้งหัวคอลัมน์และเมนู "ย้ายไป…" */
export const STAGE_LABEL: Record<BoardStage, string> = {
  invited: "เชิญแล้ว",
  scheduled: "นัดสัมภาษณ์",
  interviewed: "สัมภาษณ์แล้ว",
  offer: "ยื่นข้อเสนอ",
  hired: "รับเข้าแล้ว",
  // ⚠️ คนละเรื่องกับ "ไม่ผ่านคัดกรอง" (hr_decision='rejected') ซึ่งไม่ขึ้นกระดานตั้งแต่แรก
  // อันนี้คือหลุดระหว่างกระบวนการ เช่นผู้สมัครปฏิเสธข้อเสนอ หรือ HR ยุติการติดต่อ
  declined: "ไม่ไปต่อ",
};

export const STAGE_ORDER: BoardStage[] = [
  "invited",
  "scheduled",
  "interviewed",
  "offer",
  "hired",
  "declined",
];

/**
 * การ์ดผู้สมัครหนึ่งใบบนกระดานติดตาม
 *
 * ย้ายขั้นได้สองทางเสมอ: ลากด้วยเมาส์ หรือเลือกจากเมนู "ย้ายไป…"
 * เมนูไม่ใช่ของเสริม — บนมือถือการลากข้ามคอลัมน์แนวนอนแทบใช้ไม่ได้ และ HTML5
 * drag & drop เข้าถึงด้วยคีย์บอร์ดไม่ได้เลย เมนูจึงเป็นทางหลักของผู้ใช้สองกลุ่มนั้น
 */
export default function BoardCard({
  item,
  jobId,
  onMove,
  onDragStart,
  busy = false,
}: {
  item: BoardItem;
  jobId: string;
  onMove: (stage: BoardStage) => void;
  onDragStart: () => void;
  busy?: boolean;
}) {
  // คนที่รับเข้าเป็นพนักงานแล้วย้ายขั้นไม่ได้ — ถ้าจะแก้ต้องไปที่ระเบียนพนักงาน
  // (backend ก็ตอบ 409 อยู่แล้ว ที่นี่แค่ไม่ชวนให้กดตั้งแต่แรก)
  const locked = item.stage === "hired";
  const conf = item.confidence ? CONFIDENCE[item.confidence] : null;

  return (
    <div
      draggable={!locked && !busy}
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", item.candidate_id);
        e.dataTransfer.effectAllowed = "move";
        onDragStart();
      }}
      className={`glass-card rounded-2xl p-sm space-y-xs transition-opacity ${
        locked ? "cursor-not-allowed" : "cursor-grab active:cursor-grabbing"
      } ${busy ? "opacity-50" : ""}`}
    >
      {/* ผลคัดกรองขัดกับการที่การ์ดอยู่บนกระดาน — เตือน ไม่ซ่อนการ์ดทิ้ง
          เพราะ HR นัดคนนี้ไปแล้ว การ์ดที่หายเองแปลว่างานที่ทำไปแล้วหายไปด้วย */}
      {item.screening_conflict && (
        <div className="flex gap-base items-start p-xs rounded-lg border border-tertiary/40 bg-tertiary-container/10">
          <span
            className="material-symbols-outlined text-tertiary text-[16px] flex-none"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            warning
          </span>
          <p className="text-on-surface-variant text-label-sm leading-snug">
            ผลคัดกรองถูกเปลี่ยนเป็นปฏิเสธภายหลัง — ตรวจสอบก่อนดำเนินการต่อ
          </p>
        </div>
      )}

      <div className="flex items-start gap-xs">
        <div className="min-w-0 flex-1">
          <p className="text-label-md font-semibold text-on-surface leading-snug break-words">
            {item.full_name}
          </p>
          <div className="flex flex-wrap gap-base mt-1">
            {/* โชว์ความมั่นใจเฉพาะตอนที่ไม่ใช่ "ครบ" — ป้ายที่ขึ้นทุกใบจะกลายเป็นสิ่งที่ตาข้าม */}
            {conf && item.confidence !== "high" && (
              <span
                className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full ${conf.chip}`}
              >
                <span className="material-symbols-outlined text-[13px]">
                  {conf.icon}
                </span>
                {conf.label}
              </span>
            )}
            {item.email_sent_at && (
              <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-primary-fixed text-on-primary-fixed-variant">
                <span className="material-symbols-outlined text-[13px]">mail</span>
                ส่งอีเมลแล้ว
              </span>
            )}
          </div>
        </div>
        <ScoreRing score={item.fit_score} size={44} />
      </div>

      <div className="flex items-center gap-base flex-wrap pt-1">
        <Link
          href={`/jobs/${jobId}/candidates/${item.candidate_id}`}
          className="text-label-sm text-primary hover:underline inline-flex items-center gap-0.5"
        >
          ดูรายละเอียด
          <span className="material-symbols-outlined text-[14px]">chevron_right</span>
        </Link>

        {locked && item.employee_id ? (
          <Link
            href={`/employees/${item.employee_id}`}
            className="text-label-sm text-primary hover:underline inline-flex items-center gap-0.5 ms-auto"
          >
            <span className="material-symbols-outlined text-[14px]">badge</span>
            ระเบียนพนักงาน
          </Link>
        ) : (
          <label className="ms-auto">
            <span className="sr-only">ย้าย {item.full_name} ไปขั้นอื่น</span>
            <select
              value={item.stage}
              disabled={busy}
              onChange={(e) => onMove(e.target.value as BoardStage)}
              className="input-glass text-label-sm py-0.5 px-xs"
            >
              {STAGE_ORDER.map((s) => (
                <option key={s} value={s}>
                  {s === item.stage ? `อยู่ที่: ${STAGE_LABEL[s]}` : `ย้ายไป ${STAGE_LABEL[s]}`}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
    </div>
  );
}
