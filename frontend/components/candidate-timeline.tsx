"use client";

import Link from "next/link";
import { useState } from "react";
import { STAGE_LABEL, stageMoveWarning } from "@/components/board-card";
import ConfirmDialog from "@/components/confirm-dialog";
import { setStage } from "@/lib/api";
import { INTERVIEW_RESULT } from "@/lib/types";
import type { BoardStage, CandidateDetail } from "@/lib/types";

/**
 * เส้นทางของผู้สมัครหนึ่งคน — ประวัติที่เกิดแล้ว + ขั้นที่ยังไม่ถึง + ปุ่มย้ายขั้น ในที่เดียว
 *
 * เดิมแยกเป็นสองบล็อกบนหน้าเดียวกัน (ไทม์ไลน์อ่านอย่างเดียว กับแถบ "ความคืบหน้าหลังผ่าน
 * คัดกรอง" ที่กดได้) แล้วสามขั้น — นัดสัมภาษณ์ สัมภาษณ์แล้ว รับเข้าแล้ว — โผล่ซ้ำกันทั้งสองที่
 * โดยบอกคนละแบบ (อันหนึ่งมีเวลา อีกอันมีปุ่ม) รวมเป็นอันเดียวจึงเหลือแหล่งเดียวที่ตอบครบว่า
 * "เกิดอะไรไปแล้วเมื่อไหร่ ตอนนี้อยู่ตรงไหน และกดอะไรได้ต่อ"
 *
 * **เรียงตามลำดับของกระบวนการ ไม่ใช่ตามเวลา** — วันนัดสัมภาษณ์เป็นเวลาในอนาคต ถ้าเรียง
 * ตามเวลามันจะเด้งไปท้ายสุดแซงเหตุการณ์ที่เกิดไปแล้ว และขั้นที่ยังไม่ถึงก็ไม่มีเวลาให้เรียงอยู่ดี
 *
 * เรียงซ้ายไปขวา และขึ้นบรรทัดใหม่เองเมื่อจอแคบ (ไม่ใช่เลื่อนแนวนอน ซึ่งซ่อนขั้นท้าย ๆ ไว้)
 *
 * ⚠️ ปุ่มย้ายขั้นเรียก `setStage` ตัวเดียวกับหน้ากระดาน และสถานะปัจจุบันอ่านจาก `board_stage`
 * ที่ backend คำนวณด้วย `hiring_board.board_stage` — สองหน้าจึงไม่มีทางเห็นไม่ตรงกัน
 */

// บันไดหลักตามลำดับจริง — "ไม่ไปต่อ" อยู่นอกบันได จึงเป็นปุ่มแยก ไม่ใช่ขั้นที่ 6
const LADDER: BoardStage[] = ["invited", "scheduled", "interviewed", "offer", "hired"];

type Row = {
  key: string;
  icon: string;
  label: string;
  /** เวลาที่เกิดเหตุการณ์ — null ทั้งที่ done = เกิดแล้วแต่ไม่รู้เวลา */
  at?: string | null;
  /** เวลาเป็นวันที่ล้วน (YYYY-MM-DD) ไม่ต้องโชว์เวลานาฬิกา */
  dateOnly?: boolean;
  done: boolean;
  detail?: React.ReactNode;
  /** ขั้นบนกระดานที่กดย้ายไปได้ — ไม่มี = แถวประวัติอ่านอย่างเดียว */
  stage?: BoardStage;
  /** ปิดกระบวนการไปก่อนถึงขั้นนี้ — "ไม่ได้ไปถึง" ไม่ใช่ "ยังไม่ถึง" (ยังกดดึงกลับมาได้) */
  unreached?: boolean;
  /** ผลบวก/ลบของเหตุการณ์ (คำตัดสินของ HR) — ให้สีบอกผลได้ในแวบเดียว ไม่ต้องอ่านคำ */
  tone?: "positive" | "negative";
};

function fmt(iso: string, dateOnly: boolean): string {
  // date ล้วนต้องต่อเวลาเอง ไม่งั้นบางเบราว์เซอร์ตีเป็น UTC แล้ววันเลื่อนสำหรับโซน +07
  const d = new Date(dateOnly ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso; // ค่าผิดรูป: โชว์ดิบ ๆ ดีกว่า Invalid Date
  return d.toLocaleString("th-TH", {
    dateStyle: "medium",
    ...(dateOnly ? {} : { timeStyle: "short" }),
  });
}

/** แถวทั้งหมดตามลำดับกระบวนการ — แยกออกมาให้อ่านง่ายและแก้ลำดับที่เดียว */
function buildRows(c: CandidateDetail): Row[] {
  const decided = c.hr_decision === "approved" || c.hr_decision === "rejected";
  const onBoard = c.board_stage != null;

  const history: Row[] = [
    {
      key: "applied",
      icon: "upload_file",
      label: "รับเรซูเม่เข้าระบบ",
      at: c.created_at,
      done: true,
    },
    {
      key: "scored",
      icon: "smart_toy",
      label: "AI วิเคราะห์เสร็จ",
      at: c.evaluated_at,
      done: c.evaluated_at != null,
      detail: c.fit_score != null ? `คะแนน ${c.fit_score}` : undefined,
    },
    {
      key: "decided",
      icon: c.hr_decision === "rejected" ? "cancel" : "how_to_reg",
      label:
        c.hr_decision === "rejected"
          ? "HR ตัดสินว่าไม่ผ่าน"
          : c.hr_decision === "approved"
            ? "HR อนุมัติให้ไปต่อ"
            : "HR ตัดสิน",
      at: c.hr_decided_at,
      done: decided,
      tone:
        c.hr_decision === "approved"
          ? "positive"
          : c.hr_decision === "rejected"
            ? "negative"
            : undefined,
      detail: c.hr_notes ?? undefined,
    },
    {
      key: "email",
      icon: "mail",
      label:
        c.email_send_count > 1 ? `ส่งอีเมลแล้ว ${c.email_send_count} ครั้ง` : "ส่งอีเมล",
      at: c.email_sent_at,
      done: c.email_sent_at != null,
      detail: c.email_sent_to ?? undefined,
    },
  ];

  // ขั้นบนกระดานโผล่เฉพาะคนที่อยู่บนกระดาน — คนที่ไม่ผ่านคัดกรองไม่มีบันไดนี้ให้เดิน
  if (!onBoard) return history;

  const current = c.board_stage as BoardStage;
  const currentIdx = LADDER.indexOf(current); // -1 เมื่อ declined
  const declined = current === "declined";
  const ladder: Row[] = LADDER.map((s, i) => ({
    key: s,
    stage: s,
    icon: LADDER_ICON[s],
    label: STAGE_LABEL[s],
    // ผ่านมาแล้วหรือกำลังอยู่ที่ขั้นนี้ = เกิดแล้ว · declined ไม่มีตำแหน่งบนบันได จึงดูจาก
    // หลักฐานที่เหลืออยู่แทน (เดิมใช้ index อย่างเดียว คนที่สัมภาษณ์ไม่ผ่านแล้วปิดกระบวนการ
    // เลยขึ้นว่า "ยังไม่ถึง" ทั้งขั้นนัดและขั้นสัมภาษณ์ ทั้งที่มีวันนัดกับผลสัมภาษณ์อยู่จริง)
    done: declined ? DECLINED_EVIDENCE[s](c) : currentIdx >= 0 && i <= currentIdx,
    ...LADDER_TIME[s](c),
  }));

  // "รับเข้าแล้ว" ยึดระเบียนพนักงานเป็นหลัก เหมือนที่ backend อนุมาน stage='hired' จากตรงนั้น
  const hiredRow = ladder[LADDER.indexOf("hired")];
  hiredRow.done = hiredRow.done || c.employee_id != null;

  if (!declined) return [...history, ...ladder];

  // ปิดกระบวนการ: แทรกจุด "ไม่ไปต่อ" ต่อจากขั้นสุดท้ายที่มีหลักฐาน ให้เห็นว่าเส้นทางหยุดตรงไหน
  // ขั้นที่อยู่หลังจากนั้นไม่มีวันถึงแล้ว (เว้นแต่ HR ดึงกลับ) จึงบอกว่า "ไม่ได้ไปถึง"
  const lastReached = ladder.map((r) => r.done).lastIndexOf(true);
  const stop: Row = {
    key: "declined",
    stage: "declined",
    icon: LADDER_ICON.declined,
    label: STAGE_LABEL.declined,
    at: c.stage_moved_at,
    done: true,
  };
  const before = ladder.slice(0, lastReached + 1);
  const after = ladder
    .slice(lastReached + 1)
    .map((r) => ({ ...r, unreached: true }));
  return [...history, ...before, stop, ...after];
}

const LADDER_ICON: Record<BoardStage, string> = {
  invited: "flag",
  scheduled: "event",
  interviewed: "record_voice_over",
  offer: "handshake",
  hired: "badge",
  declined: "block",
};

/** เวลาที่รู้จริงของแต่ละขั้น — hiring_stage เก็บแถวเดียวต่อคน จึงมีเวลาเฉพาะขั้นล่าสุด */
const LADDER_TIME: Record<
  BoardStage,
  (c: CandidateDetail) => Partial<Row>
> = {
  invited: (c) => (c.board_stage === "invited" ? { at: c.stage_moved_at } : {}),
  scheduled: (c) => ({ at: c.scheduled_at, detail: c.location ?? undefined }),
  interviewed: (c) => ({
    at: c.interview_outcome?.interviewed_at,
    dateOnly: true,
    detail: c.interview_outcome ? (
      <span
        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-label-sm font-semibold ${
          INTERVIEW_RESULT[c.interview_outcome.result].chip
        }`}
      >
        <span className="material-symbols-outlined text-[14px]" aria-hidden>
          {INTERVIEW_RESULT[c.interview_outcome.result].icon}
        </span>
        {INTERVIEW_RESULT[c.interview_outcome.result].label}
      </span>
    ) : undefined,
  }),
  // วันที่ยื่นมาจากตาราง job_offers ซึ่งอยู่ต่อแม้ขั้นเปลี่ยน · ไม่มีข้อเสนอที่บันทึกไว้
  // (ลากการ์ดมาบนกระดาน) ใช้เวลาย้ายขั้นแทนเฉพาะตอนที่ยังอยู่ขั้นนี้
  offer: (c) => ({
    at: c.offer?.offered_at ?? (c.board_stage === "offer" ? c.stage_moved_at : undefined),
    detail: c.offer ? (
      <span
        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-label-sm font-semibold ${
          OFFER_RESPONSE[c.offer.response].chip
        }`}
      >
        {OFFER_RESPONSE[c.offer.response].label}
      </span>
    ) : undefined,
  }),
  hired: (c) => ({ at: c.hired_at }),
  declined: () => ({}),
};

/** ป้ายคำตอบข้อเสนอบนไทม์ไลน์ — โทนเดียวกับป้ายผลสัมภาษณ์ */
const OFFER_RESPONSE: Record<
  NonNullable<CandidateDetail["offer"]>["response"],
  { label: string; chip: string }
> = {
  pending: {
    label: "รอคำตอบ",
    chip: "bg-primary-container/40 text-on-primary-container",
  },
  accepted: {
    label: "ตอบรับ",
    chip: "bg-secondary-container/40 text-on-secondary-container",
  },
  declined: {
    label: "ปฏิเสธ",
    chip: "bg-error-container/50 text-on-error-container",
  },
};

/**
 * คนที่อยู่ "ไม่ไปต่อ" เคยผ่านขั้นไหนมาแล้วบ้าง — hiring_stage เก็บแถวเดียว (ขั้นล่าสุด)
 * พอย้ายไป declined ขั้นเดิมก็หายไป จึงอนุมานจากร่องรอยที่ยังอยู่ในตารางอื่นแทน
 * "ยื่นข้อเสนอ" ดูจาก job_offers — ข้อเสนอที่ลากการ์ดมาโดยไม่บันทึกรายละเอียดจึงไม่นับ
 */
const DECLINED_EVIDENCE: Record<BoardStage, (c: CandidateDetail) => boolean> = {
  invited: () => true, // มีแถวบนกระดานแล้วแปลว่าผ่านคัดกรองขึ้นกระดานมา
  scheduled: (c) => c.scheduled_at != null || c.interview_outcome != null,
  interviewed: (c) => c.interview_outcome != null,
  offer: (c) => c.offer != null,
  hired: (c) => c.employee_id != null,
  declined: () => true,
};

export default function CandidateTimeline({
  candidate: c,
  candidateId,
  jobId,
  onChanged,
  onHire,
}: {
  candidate: CandidateDetail;
  candidateId: string;
  jobId: string;
  onChanged: () => void;
  onHire: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{
    next: BoardStage;
    title: string;
    body: string;
  } | null>(null);

  const stage = c.board_stage;
  const locked = stage === "hired";
  const declined = stage === "declined";
  const rows = buildRows(c);
  // แถวที่ยังไม่เกิดแต่มีเรื่องหลังจากนั้นเกิดไปแล้ว = ถูกข้าม ไม่ใช่ "ยังไม่ถึง"
  const lastDone = rows.map((r) => r.done).lastIndexOf(true);

  async function commit(next: BoardStage) {
    setBusy(true);
    setError(null);
    try {
      await setStage(candidateId, next);
      setPending(null);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "ย้ายขั้นไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  function request(next: BoardStage) {
    if (locked || busy || next === stage) return;
    // "รับเข้าแล้ว" = สร้างระเบียนพนักงาน ต้องกรอกข้อมูลการจ้าง ไม่ใช่แค่ย้ายขั้น
    if (next === "hired") return onHire();
    const warn = stageMoveWarning(stage ?? "invited", next, c.interview_outcome != null);
    if (warn) setPending({ next, ...warn });
    else commit(next);
  }

  return (
    <section className="glass-card rounded-2xl p-md" aria-labelledby="timeline-h">
      <div className="flex items-start justify-between gap-sm flex-wrap mb-sm">
        <div>
          <h3
            id="timeline-h"
            className="text-headline-md text-on-surface flex items-center gap-xs"
          >
            <span className="material-symbols-outlined text-primary">timeline</span>
            เส้นทางของผู้สมัคร
          </h3>
          <p className="text-label-sm text-on-surface-variant">
            {stage
              ? locked
                ? "รับเข้าเป็นพนักงานแล้ว — แก้ไขได้ที่ระเบียนพนักงาน"
                : "กดขั้นด้านล่างเพื่อย้ายเมื่อมีความคืบหน้า"
              : "ยังไม่อยู่บนกระดานติดตาม — แสดงเฉพาะสิ่งที่เกิดขึ้นแล้ว"}
          </p>
        </div>
        {stage && (
          <Link
            href={`/jobs/${jobId}/board`}
            className="text-label-md text-primary hover:underline inline-flex items-center gap-0.5"
          >
            ดูบนกระดาน
            <span className="material-symbols-outlined text-[16px]">chevron_right</span>
          </Link>
        )}
      </div>

      {declined && (
        <p className="text-label-md text-on-surface-variant flex items-center gap-xs mb-sm">
          <span className="material-symbols-outlined text-[18px] text-outline">block</span>
          อยู่ที่ “ไม่ไปต่อ” — กดขั้นใดขั้นหนึ่งเพื่อดึงกลับเข้ากระบวนการ
        </p>
      )}

      {/* จอ sm ขึ้นไป: ซ้ายไปขวา และ **ขึ้นบรรทัดใหม่เองเมื่อจอแคบ** (flex-wrap) ไม่ใช่เลื่อนแนวนอน —
          แถบเลื่อนแนวนอนซ่อนขั้นท้าย ๆ ไว้จนไม่มีใครเห็น
          มือถือ: เรียงลงแนวตั้ง ไอคอนซ้าย ข้อความขวา ลูกศรชี้ลง — เดิมใช้ flex-wrap ด้วย การ์ดในหน้าผู้สมัคร
          แคบจนได้แถวละ 1 ขั้น ลูกศรจึงชี้ไปทางขวาทั้งที่ขั้นถัดไปอยู่ข้างล่าง และขั้นสุดท้าย (ไม่มีลูกศร)
          หลุดไปอยู่ข้างขั้นก่อนหน้า (เจอตอนตรวจมือถือ 2026-10-12) */}
      <ol className="flex flex-col sm:flex-row sm:flex-wrap items-start sm:gap-y-sm">
        {rows.map((r, i) => {
          const isCurrent = r.stage != null && r.stage === stage;
          const clickable = r.stage != null && !locked && !isCurrent && !busy;
          const when = r.at
            ? fmt(r.at, Boolean(r.dateOnly))
            : r.done
              ? "ไม่ได้ระบุเวลา"
              : r.unreached
                ? "ไม่ได้ไปถึง"
                : i < lastDone
                  ? "ไม่มีข้อมูล"
                  : "ยังไม่ถึงขั้นนี้";
          return (
            <li key={r.key} className="flex flex-col sm:flex-row items-start w-full sm:w-auto">
              <div
                className={`w-full sm:w-[124px] flex sm:flex-col items-start sm:items-center text-left sm:text-center gap-sm sm:gap-0.5 ${
                  r.done ? "" : "opacity-60"
                }`}
              >
                <span
                  aria-hidden
                  className={`w-9 h-9 rounded-full flex items-center justify-center ${
                    isCurrent
                      ? "bg-primary/15 text-primary ring-2 ring-primary"
                      : r.done && r.tone === "positive"
                        ? // โทนเดียวกับกล่อง "ผ่านคัดกรองแล้ว" ในการ์ดผลคัดกรอง — ไม่ยืมสีแบนด์คะแนน
                          "bg-secondary-container/40 text-secondary"
                        : r.done && r.tone === "negative"
                          ? "bg-error-container/40 text-error"
                          : r.done
                            ? "bg-primary/10 text-primary"
                            : "bg-glass/60 border border-outline/40 text-on-surface-variant"
                  }`}
                >
                  <span className="material-symbols-outlined text-[18px]">{r.icon}</span>
                </span>

                <div className="flex flex-col items-start sm:items-center gap-0.5 min-w-0">

                  {r.stage ? (
                    <button
                      type="button"
                      onClick={() => request(r.stage as BoardStage)}
                      disabled={!clickable}
                      aria-current={isCurrent ? "step" : undefined}
                      title={clickable ? "กดเพื่อย้ายมาขั้นนี้" : undefined}
                      className={`text-label-md font-semibold leading-tight disabled:cursor-default ${
                        isCurrent ? "text-primary" : "text-on-surface"
                      } ${clickable ? "hover:text-primary hover:underline" : ""}`}
                    >
                      {r.label}
                    </button>
                  ) : (
                    <p
                      className={`text-label-md font-semibold leading-tight ${
                        r.tone === "positive"
                          ? "text-secondary"
                          : r.tone === "negative"
                            ? "text-error"
                            : "text-on-surface"
                      }`}
                    >
                      {r.label}
                    </p>
                  )}

                  {isCurrent && (
                    <span className="text-label-sm font-semibold px-2 py-0.5 rounded-full bg-primary/15 text-primary">
                      ตอนนี้อยู่ขั้นนี้
                    </span>
                  )}
                  <p className="text-label-sm text-on-surface-variant leading-tight">{when}</p>
                  {r.detail && (
                    <div className="text-label-sm text-on-surface-variant break-words">
                      {r.detail}
                    </div>
                  )}
                </div>
              </div>

              {/* ลูกศรคั่น — จอ sm ขึ้นไปอยู่ระดับเดียวกับวงกลม (วงกลมสูง 36px จึงเยื้องลงครึ่งหนึ่ง)
                  มือถือหมุนชี้ลง อยู่กึ่งกลางใต้วงกลม (เยื้องขวาครึ่งหนึ่งของ 36−18) */}
              {i < rows.length - 1 && (
                <span
                  aria-hidden
                  className={`material-symbols-outlined text-[18px] rotate-90 sm:rotate-0 ml-[9px] my-0.5 sm:ml-0 sm:my-0 sm:mt-[9px] ${
                    i < lastDone ? "text-primary/50" : "text-outline"
                  }`}
                >
                  chevron_right
                </span>
              )}
            </li>
          );
        })}
      </ol>

      {/* ขั้นสัมภาษณ์แล้ว/ยื่นข้อเสนอ การ์ดท้ายหน้ามีปุ่มปิดกระบวนการของมันเองอยู่แล้ว —
          ไม่ซ้ำปุ่มเดียวกันสองที่ */}
      {stage && !locked && !declined && stage !== "interviewed" && stage !== "offer" && (
        <button
          onClick={() => request("declined")}
          disabled={busy}
          className="text-label-sm text-on-surface-variant hover:text-error inline-flex items-center gap-1"
        >
          <span className="material-symbols-outlined text-[16px]">block</span>
          ย้ายไป “ไม่ไปต่อ” (ผู้สมัครถอนตัว หรือยุติการติดต่อ)
        </button>
      )}

      {error && !pending && (
        <p className="text-error text-label-md mt-xs" role="alert">
          {error}
        </p>
      )}

      {pending && (
        <ConfirmDialog
          title={pending.title}
          body={<p>{pending.body}</p>}
          confirmLabel={`ย้ายไป “${STAGE_LABEL[pending.next]}”`}
          busy={busy}
          error={error}
          onConfirm={() => commit(pending.next)}
          onClose={() => {
            setPending(null);
            setError(null);
          }}
        />
      )}
    </section>
  );
}
