"use client";

import Link from "next/link";
import { InterviewScheduleSummary } from "@/components/interview-schedule";
import ScoreRing from "@/components/score-ring";
import { CONFIDENCE, INTERVIEW_RESULT } from "@/lib/types";
import type { BoardItem, BoardStage } from "@/lib/types";

/** ป้ายของแต่ละคอลัมน์ — ใช้ร่วมกันทั้งหัวคอลัมน์และเมนู "ย้ายไป…" */
// ⚠️ ป้ายต้องบอก "สถานะที่เป็นจริงแน่ ๆ" เท่านั้น — เดิม invited ชื่อ "เชิญแล้ว"
// ทั้งที่ไม่มีใครเชิญใคร: backend ใส่ทุกคนที่ผ่านคัดกรองไว้ขั้นนี้แบบคำนวณเอง
// (ดู hiring_board.py::get_board) HR อ่านแล้วเข้าใจว่าระบบส่งคำเชิญไปแล้ว
export const STAGE_LABEL: Record<BoardStage, string> = {
  invited: "รอติดต่อ",
  scheduled: "นัดสัมภาษณ์แล้ว",
  interviewed: "สัมภาษณ์แล้ว",
  offer: "ยื่นข้อเสนอ",
  hired: "รับเข้าแล้ว",
  // ⚠️ คนละเรื่องกับ "ไม่ผ่านคัดกรอง" (hr_decision='rejected') ซึ่งไม่ขึ้นกระดานตั้งแต่แรก
  // อันนี้คือหลุดระหว่างกระบวนการ เช่นผู้สมัครปฏิเสธข้อเสนอ หรือ HR ยุติการติดต่อ
  declined: "ไม่ไปต่อ",
};

/** คำอธิบายใต้หัวคอลัมน์ — ตอบว่า "คนในคอลัมน์นี้คือใคร" ให้ HR ไม่ต้องเดา */
export const STAGE_HINT: Record<BoardStage, string> = {
  invited: "ผ่านคัดกรองแล้ว ยังไม่ได้นัด",
  scheduled: "มีวันนัดแล้ว รอสัมภาษณ์",
  interviewed: "สัมภาษณ์เสร็จ รอตัดสินใจ",
  offer: "ส่งข้อเสนอแล้ว รอตอบรับ",
  hired: "ย้ายมาที่นี่เพื่อบันทึกการจ้าง",
  declined: "ถอนตัวหรือยุติระหว่างทาง",
};

/**
 * ด่านถามยืนยันเฉพาะการย้ายที่ "ขัดกับข้อมูลที่บันทึกไว้" — ถามแต่ไม่บล็อก
 *
 * ไม่ล็อกให้เดินทีละขั้นโดยตั้งใจ: งานจริงข้ามขั้นได้ (ลงข้อมูลย้อนหลัง, สัมภาษณ์ก่อนเข้าระบบ)
 * และต้องย้อนได้เพื่อแก้การลากผิด ถ้าล็อกแข็ง HR จะลากผ่านทีละคอลัมน์ให้ครบ
 * ซึ่งทำให้ moved_at เพี้ยนกว่าเดิม · ถามเฉพาะสองกรณีที่การ์ดจะบอกข้อมูลขัดกันเอง
 *
 * ใช้ร่วมกันทั้งหน้ากระดานและแถบขั้นตอนในหน้ารายละเอียด ให้กฎมีชุดเดียว
 */
export function stageMoveWarning(
  current: BoardStage,
  next: BoardStage,
  hasInterviewResult: boolean,
): { title: string; body: string } | null {
  if (hasInterviewResult && (next === "invited" || next === "scheduled")) {
    return {
      title: `ย้อนกลับไป “${STAGE_LABEL[next]}”?`,
      body:
        "ผู้สมัครรายนี้มีผลสัมภาษณ์บันทึกไว้แล้ว ถ้าย้อนขั้น การ์ดจะบอกว่ายังไม่ได้สัมภาษณ์ " +
        "ทั้งที่มีผลอยู่ (ผลสัมภาษณ์จะไม่ถูกลบ)",
    };
  }
  if (!hasInterviewResult && next === "offer" && (current === "invited" || current === "scheduled")) {
    return {
      title: "ข้ามไป “ยื่นข้อเสนอ” โดยยังไม่มีผลสัมภาษณ์?",
      body:
        "ยังไม่มีผลสัมภาษณ์บันทึกไว้ ถ้าสัมภาษณ์ไปแล้ว แนะนำให้บันทึกผลในหน้ารายละเอียดก่อน " +
        "เพื่อให้ย้อนดูเหตุผลที่ยื่นข้อเสนอได้",
    };
  }
  return null;
}

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
  jobTitle,
  onMove,
  onDragStart,
  onSchedule,
  busy = false,
}: {
  item: BoardItem;
  jobId: string;
  /** ใช้ตั้งหัวข้อ event ในปฏิทิน */
  jobTitle?: string | null;
  onMove: (stage: BoardStage) => void;
  onDragStart: () => void;
  /** เปิดโมดัลกรอกวันนัด — โผล่เฉพาะการ์ดในคอลัมน์ "นัดสัมภาษณ์แล้ว" */
  onSchedule?: () => void;
  busy?: boolean;
}) {
  // คนที่รับเข้าเป็นพนักงานแล้วย้ายขั้นไม่ได้ — ถ้าจะแก้ต้องไปที่ระเบียนพนักงาน
  // (backend ก็ตอบ 409 อยู่แล้ว ที่นี่แค่ไม่ชวนให้กดตั้งแต่แรก)
  const locked = item.stage === "hired";
  const conf = item.confidence ? CONFIDENCE[item.confidence] : null;
  // ขึ้นทุกคอลัมน์ที่มีผล ไม่ใช่เฉพาะ "สัมภาษณ์แล้ว" — พอย้ายไป "ยื่นข้อเสนอ" แล้ว
  // HR ก็ยังต้องเห็นว่าผลสัมภาษณ์ออกมายังไงโดยไม่ต้องเปิดเข้าไปดู
  const outcome = item.interview_result
    ? INTERVIEW_RESULT[item.interview_result]
    : null;

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
            {outcome && (
              <span
                className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full ${outcome.chip}`}
              >
                <span className="material-symbols-outlined text-[13px]">
                  {outcome.icon}
                </span>
                {outcome.label}
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
        {/* ไม่โชว์ป้ายแบนด์ใต้วง: คนบนกระดานผ่านคัดกรองมาแล้วทุกคน ป้าย "NEEDS REVIEW"
            ของคนที่ HR อนุมัติไปแล้วอ่านเหมือนยังค้างรอตัดสิน */}
        <ScoreRing score={item.fit_score} size={44} showLabel={false} />
      </div>

      {/* วันนัดโชว์เฉพาะคอลัมน์ "นัดสัมภาษณ์แล้ว" — ขั้นอื่นวันนัดไม่ใช่สิ่งที่ต้องทำต่อแล้ว
          (ข้อมูลยังเก็บไว้ ย้ายขั้นไม่ลบวันนัด และยังเห็นได้ในหน้ารายละเอียด) */}
      {item.stage === "scheduled" &&
        (item.scheduled_at ? (
          <InterviewScheduleSummary
            compact
            scheduledAt={item.scheduled_at}
            location={item.location}
            candidateName={item.full_name}
            jobTitle={jobTitle}
            onEdit={busy ? undefined : onSchedule}
          />
        ) : (
          onSchedule && (
            <button
              type="button"
              className="btn-tonal w-full justify-center text-label-sm"
              onClick={onSchedule}
              disabled={busy}
            >
              <span className="material-symbols-outlined text-[16px]">edit_calendar</span>
              ตั้งวันเวลานัด
            </button>
          )
        ))}

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
