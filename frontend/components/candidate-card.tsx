"use client";

import Link from "next/link";
import { useState } from "react";
import { deleteCandidate, reprocessCandidate } from "@/lib/api";
import type { CandidateSummary } from "@/lib/types";
import { QUEUE_STATE } from "@/lib/types";
import { skillLabel } from "@/lib/skill-group";
import CandidateAvatar, { useScreeningPhotos } from "./candidate-avatar";
import ConfirmDialog from "./confirm-dialog";
import ScoreRing from "./score-ring";
import Spinner from "@/components/spinner";

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
  selectable = false,
  selected = false,
  onSelectChange,
}: {
  jobId: string;
  candidate: CandidateSummary;
  index: number;
  matched?: string[];
  missing?: string[];
  /** เรียกหลังกระทำสำเร็จ (วิเคราะห์ใหม่ / ลบ) เพื่อให้หน้าแม่ revalidate */
  onChanged?: () => void;
  /** ติ๊กเลือกเพื่อตัดสินหมู่ได้ไหม — เฉพาะคนที่กราฟรอ HR อยู่จริง */
  selectable?: boolean;
  selected?: boolean;
  onSelectChange?: (checked: boolean) => void;
}) {
  // หน้ารายชื่อยังมีการตัดสิน (ติ๊กเลือกตัดสินหมู่) → รูปขึ้นเฉพาะเมื่อ HR เปิดสวิตช์
  const showPhoto = useScreeningPhotos();
  const [busy, setBusy] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  // งานยังอยู่ในคิวฝั่ง backend — ระบบจะรันให้เอง ไม่ต้องให้ HR กดอะไร
  const queued = candidate.queue_status
    ? QUEUE_STATE[candidate.queue_status]
    : null;
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
    <div
      className={`glass-card rounded-2xl px-md py-sm flex items-center gap-md flex-wrap ${
        selected ? "ring-2 ring-primary" : ""
      }`}
    >
      {/* ติ๊กเลือกเฉพาะคนที่ตัดสินได้จริง — คนอื่นเว้นที่ว่างไว้ให้การ์ดเรียงตรงกัน */}
      {selectable ? (
        <input
          type="checkbox"
          checked={selected}
          onChange={(e) => onSelectChange?.(e.target.checked)}
          aria-label={`เลือก ${candidate.full_name}`}
          className="flex-none w-5 h-5 accent-primary cursor-pointer"
        />
      ) : (
        <span className="flex-none w-5" aria-hidden />
      )}
      <CandidateAvatar
        candidateId={candidate.id}
        name={candidate.full_name}
        show={showPhoto}
        className="w-12 h-12 flex-none rounded-xl flex items-center justify-center text-body-md font-semibold text-white"
        style={{ background: AVATAR_COLORS[index % AVATAR_COLORS.length] }}
      />

      <div className="flex-[2] min-w-[180px]">
        <div className="text-body-md font-semibold text-on-surface mb-0.5">
          {candidate.full_name}
        </div>
        <div className="text-label-md text-on-surface-variant mb-xs">
          {candidate.email ?? "—"}
        </div>
        {queued && (
          <div className="mb-xs">
            <span
              className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1 rounded-full ${queued.chip}`}
            >
              {candidate.queue_status === "running" ? (
                <Spinner className="text-[14px]" />
              ) : (
                <span className="material-symbols-outlined text-[14px]">{queued.icon}</span>
              )}
              {queued.label}
            </span>
          </div>
        )}
        {/* HR แก้เกณฑ์ทักษะจนคะแนนข้ามแบนด์ — ระบบไม่ทำอะไรเอง ให้คนตัดสินใหม่ */}
        {candidate.needs_recheck && (
          <div className="mb-xs">
            <span
              className="inline-flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1 rounded-full bg-tertiary-fixed text-on-tertiary-fixed-variant"
              title="คะแนนถูกคำนวณใหม่หลังแก้เกณฑ์ทักษะ และข้ามแบนด์จากตอนที่ตัดสินไว้"
            >
              <span className="material-symbols-outlined text-[14px]">rule</span>
              เกณฑ์เปลี่ยน ตรวจอีกครั้ง (เดิม {candidate.rescored_from})
            </span>
          </div>
        )}
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
              className="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-secondary-fixed text-on-secondary-fixed-variant"
            >
              {skillLabel(s)}
            </span>
          ))}
          {missing.slice(0, 3).map((s) => (
            <span
              key={s}
              className="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-error/10 text-on-error-container"
            >
              {skillLabel(s)}
            </span>
          ))}
        </div>
      </div>

      <ScoreRing score={candidate.fit_score} working={candidate.queue_status === "running"} />

      <div className="flex-none flex items-center gap-xs">
        {candidate.stalled && !queued && (
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
            {busy && <Spinner className="text-[16px]" />}
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
