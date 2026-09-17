"use client";

import Link from "next/link";
import { useState } from "react";
import { STAGE_LABEL, stageMoveWarning } from "@/components/board-card";
import ConfirmDialog from "@/components/confirm-dialog";
import { setStage } from "@/lib/api";
import type { BoardStage } from "@/lib/types";

// บันไดหลักตามลำดับจริง — "ไม่ไปต่อ" อยู่นอกบันได จึงเป็นปุ่มแยก ไม่ใช่ขั้นที่ 6
const LADDER: BoardStage[] = ["invited", "scheduled", "interviewed", "offer", "hired"];

/**
 * แถบขั้นตอนบนหน้ารายละเอียดผู้สมัคร — กระจกเงาของกระดานติดตาม
 *
 * เดิมหน้านี้ไม่รู้ขั้นเลย HR เห็นแค่ "อนุมัติแล้ว" ค้างไว้ ขณะที่กระดานบอกว่ายื่นข้อเสนอไปแล้ว
 * ตอนนี้อ่าน board_stage จาก API ตัวเดียวกับกระดาน และย้ายขั้นผ่าน endpoint เดียวกัน
 * สองหน้าจึงไม่มีทางเห็นไม่ตรงกัน
 */
export default function StageStepper({
  candidateId,
  jobId,
  stage,
  movedAt,
  hasInterviewResult,
  onChanged,
  onHire,
}: {
  candidateId: string;
  jobId: string;
  stage: BoardStage;
  movedAt: string | null;
  hasInterviewResult: boolean;
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

  const locked = stage === "hired";
  const declined = stage === "declined";
  const currentIdx = LADDER.indexOf(stage); // -1 เมื่อ declined

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
    const warn = stageMoveWarning(stage, next, hasInterviewResult);
    if (warn) setPending({ next, ...warn });
    else commit(next);
  }

  return (
    <section className="glass-card rounded-2xl p-md space-y-sm" aria-labelledby="stage-h">
      <div className="flex items-center justify-between gap-sm flex-wrap">
        <div>
          <h3 id="stage-h" className="text-headline-md text-on-surface">
            ความคืบหน้าหลังผ่านคัดกรอง
          </h3>
          <p className="text-label-sm text-on-surface-variant">
            {movedAt
              ? `อัปเดตล่าสุด ${new Date(movedAt).toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short" })}`
              : "ยังไม่เคยย้ายขั้น — กดขั้นด้านล่างเมื่อมีความคืบหน้า"}
          </p>
        </div>
        <Link
          href={`/jobs/${jobId}/board`}
          className="text-label-md text-primary hover:underline inline-flex items-center gap-0.5"
        >
          ดูบนกระดาน
          <span className="material-symbols-outlined text-[16px]">chevron_right</span>
        </Link>
      </div>

      {declined && (
        <p className="text-label-md text-on-surface-variant flex items-center gap-xs">
          <span className="material-symbols-outlined text-[18px] text-outline">block</span>
          อยู่ที่ “ไม่ไปต่อ” — กดขั้นใดขั้นหนึ่งเพื่อดึงกลับเข้ากระบวนการ
        </p>
      )}

      <ol className="flex flex-wrap gap-xs" aria-label="ขั้นตอน">
        {LADDER.map((s, i) => {
          const isCurrent = s === stage;
          const isDone = !declined && i < currentIdx;
          const tone = isCurrent
            ? "border-primary bg-primary/15 text-primary font-semibold"
            : isDone
              ? "border-primary/30 text-on-surface"
              : "border-outline/30 text-on-surface-variant";
          return (
            <li key={s} className="flex items-center gap-xs">
              <button
                onClick={() => request(s)}
                disabled={locked || busy || isCurrent}
                aria-current={isCurrent ? "step" : undefined}
                className={`inline-flex items-center gap-1 px-sm py-1 rounded-full border text-label-md transition-colors disabled:cursor-default ${tone} ${
                  !locked && !isCurrent ? "hover:border-primary hover:text-primary" : ""
                } ${declined ? "opacity-70" : ""}`}
              >
                <span
                  className="material-symbols-outlined text-[16px]"
                  style={isDone || isCurrent ? { fontVariationSettings: "'FILL' 1" } : undefined}
                  aria-hidden
                >
                  {isDone ? "check_circle" : isCurrent ? "radio_button_checked" : "radio_button_unchecked"}
                </span>
                {STAGE_LABEL[s]}
              </button>
              {i < LADDER.length - 1 && (
                <span className="material-symbols-outlined text-[16px] text-outline" aria-hidden>
                  chevron_right
                </span>
              )}
            </li>
          );
        })}
      </ol>

      {!locked && !declined && (
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
        <p className="text-error text-label-md" role="alert">
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
