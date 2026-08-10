"use client";

import Link from "next/link";
import { useState } from "react";
import { deleteCandidate, reprocessCandidate } from "@/lib/api";
import type { CandidateSummary } from "@/lib/types";
import { initials } from "@/lib/types";
import ConfirmDialog from "./confirm-dialog";
import ScoreRing from "./score-ring";

const AVATAR_COLORS = [
  "#0058be",
  "#2170e4",
  "#006c49",
  "#825100",
  "#427e9e",
  "#5a4fcf",
];

// การ์ดผู้สมัครหนึ่งราย — ตาม mockup Candidate List
export default function CandidateCard({
  jobId,
  candidate,
  index,
  matched = [],
  missing = [],
  onChanged,
}: {
  jobId: string;
  candidate: CandidateSummary;
  index: number;
  matched?: string[];
  missing?: string[];
  /** เรียกหลังกระทำสำเร็จ (วิเคราะห์ใหม่ / ลบ) เพื่อให้หน้าแม่ revalidate */
  onChanged?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function retry() {
    setBusy(true);
    setRetryError(null);
    try {
      await reprocessCandidate(candidate.id);
      onChanged?.();
    } catch (e) {
      setRetryError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function doDelete() {
    setBusy(true);
    setDeleteError(null);
    try {
      await deleteCandidate(candidate.id);
      setConfirmDelete(false);
      onChanged?.();
    } catch (e) {
      // 409 = เคยส่งอีเมลถึงคนนี้แล้ว / กำลังวิเคราะห์อยู่
      setDeleteError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="glass-card rounded-2xl px-md py-sm flex items-center gap-md flex-wrap">
      <div
        className="w-12 h-12 flex-none rounded-xl flex items-center justify-center text-body-md font-semibold text-white"
        style={{ background: AVATAR_COLORS[index % AVATAR_COLORS.length] }}
      >
        {initials(candidate.full_name)}
      </div>

      <div className="flex-[2] min-w-[180px]">
        <div className="text-body-md font-semibold text-on-surface mb-0.5">
          {candidate.full_name}
        </div>
        <div className="text-label-md text-on-surface-variant mb-xs">
          {candidate.email ?? "—"}
        </div>
        {candidate.stalled && (
          <div className="mb-xs space-y-0.5">
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1 rounded-full bg-error-container/60 text-on-error-container">
              <span className="material-symbols-outlined text-[14px]">
                error
              </span>
              วิเคราะห์ไม่สำเร็จ
            </span>
            {retryError && (
              <p className="text-error text-label-sm" role="alert">
                {retryError}
              </p>
            )}
          </div>
        )}
        <div className="flex gap-base flex-wrap">
          {matched.slice(0, 4).map((s) => (
            <span
              key={s}
              className="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-secondary-fixed/60 text-on-secondary-container"
            >
              {s}
            </span>
          ))}
          {missing.slice(0, 3).map((s) => (
            <span
              key={s}
              className="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-error/10 text-on-error-container"
            >
              {s}
            </span>
          ))}
        </div>
      </div>

      <ScoreRing score={candidate.fit_score} />

      <div className="flex-none flex items-center gap-xs">
        {candidate.stalled && (
          <button
            onClick={retry}
            disabled={busy}
            className="btn-secondary-glass"
            aria-label={`วิเคราะห์ ${candidate.full_name} ใหม่`}
          >
            <span
              className={`material-symbols-outlined text-[18px] ${busy ? "animate-spin" : ""}`}
            >
              refresh
            </span>
            {busy ? "กำลังเริ่ม…" : "วิเคราะห์ใหม่"}
          </button>
        )}
        <Link
          href={`/jobs/${jobId}/candidates/${candidate.id}`}
          aria-label={`ดูรายละเอียดของ ${candidate.full_name}`}
          className="btn-tonal"
        >
          ดูรายละเอียด
          <span className="material-symbols-outlined text-[18px]">
            chevron_right
          </span>
        </Link>

        <button
          onClick={() => {
            setDeleteError(null);
            setConfirmDelete(true);
          }}
          disabled={busy}
          aria-label={`ลบ ${candidate.full_name}`}
          title="ลบผู้สมัคร"
          className="w-9 h-9 rounded-lg flex items-center justify-center text-on-surface-variant
                     hover:bg-error/5 hover:text-error active:scale-95 duration-150
                     focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-error
                     disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-[20px]">delete</span>
        </button>
      </div>

      {confirmDelete && (
        <ConfirmDialog
          title={`ลบ "${candidate.full_name}" ออกจากตำแหน่งนี้?`}
          danger
          confirmLabel="ลบถาวร"
          busy={busy}
          error={deleteError}
          body={
            <>
              <p>
                คะแนน ผลวิเคราะห์ ประวัติการตัดสินใจ และข้อมูลค้นหาเชิงความหมายของผู้สมัครรายนี้
                จะถูกลบไปด้วย และกู้คืนไม่ได้
              </p>
              <p>
                ไม่กระทบตำแหน่งงานหรือผู้สมัครรายอื่น — ถ้าอัปโหลดผิดไฟล์
                ลบแล้วอัปโหลดไฟล์ที่ถูกต้องเข้ามาใหม่ได้เลย
              </p>
            </>
          }
          onConfirm={doDelete}
          onClose={() => setConfirmDelete(false)}
        />
      )}
    </div>
  );
}
