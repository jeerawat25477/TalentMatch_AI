"use client";

import { useEffect, useRef, useState } from "react";
import ConfirmDialog from "@/components/confirm-dialog";
import { deleteJob, setJobStatus } from "@/lib/api";
import type { JobListItem } from "@/lib/types";

/**
 * เมนู ⋯ บนการ์ดตำแหน่งงาน — ปิด/เปิดรับสมัคร และลบถาวร.
 *
 * ปิดรับสมัครทำทันทีเพราะย้อนกลับได้ ส่วนการลบต้องผ่านกล่องยืนยันเสมอ
 * (และต้องพิมพ์ชื่อตำแหน่งถ้ามีผู้สมัครติดไปด้วย)
 */
export default function JobActions({
  job,
  onChanged,
  onError,
}: {
  job: JobListItem;
  onChanged: () => void;
  onError: (msg: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  const closed = job.status === "closed";

  // ปิด popover ด้วย Esc หรือคลิกนอกเมนู
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const onClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  async function toggleStatus() {
    setOpen(false);
    setBusy(true);
    try {
      await setJobStatus(job.id, closed ? "open" : "closed");
      onChanged();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function doDelete() {
    setBusy(true);
    setDeleteError(null);
    try {
      await deleteJob(job.id);
      setConfirmDelete(false);
      onChanged();
    } catch (e) {
      // 409 = เคยส่งอีเมลแล้ว / กำลังประมวลผล — ข้อความจาก backend อธิบายทางออกไว้แล้ว
      setDeleteError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={busy}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`ตัวเลือกของ ${job.title}`}
        className="w-8 h-8 rounded-lg flex items-center justify-center text-on-surface-variant
                   hover:bg-glass hover:text-on-surface active:scale-95 duration-150
                   focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary
                   disabled:opacity-50"
      >
        <span className="material-symbols-outlined text-[20px]">more_vert</span>
      </button>

      {open && (
        <div
          role="menu"
          className="glass-card-elevated rounded-xl p-base absolute right-0 top-9 w-52 z-20 flex flex-col"
        >
          <button
            role="menuitem"
            onClick={toggleStatus}
            className="text-left text-label-md text-on-surface px-sm py-xs rounded-lg
                       hover:bg-glass flex items-center gap-xs"
          >
            <span className="material-symbols-outlined text-[18px]">
              {closed ? "lock_open" : "lock"}
            </span>
            {closed ? "เปิดรับสมัครอีกครั้ง" : "ปิดรับสมัคร"}
          </button>
          <button
            role="menuitem"
            onClick={() => {
              setOpen(false);
              setDeleteError(null);
              setConfirmDelete(true);
            }}
            className="text-left text-label-md text-error px-sm py-xs rounded-lg
                       hover:bg-error/5 flex items-center gap-xs"
          >
            <span className="material-symbols-outlined text-[18px]">delete</span>
            ลบตำแหน่งงาน
          </button>
        </div>
      )}

      {confirmDelete && (
        <ConfirmDialog
          title={`ลบ "${job.title}" ถาวร?`}
          danger
          confirmLabel="ลบถาวร"
          busy={busy}
          error={deleteError}
          requireTypedText={job.candidate_count > 0 ? job.title : undefined}
          body={
            <>
              <p>
                {job.candidate_count > 0
                  ? `ผู้สมัคร ${job.candidate_count} คนพร้อมคะแนน ประวัติการตัดสินใจ และข้อมูลค้นหาเชิงความหมาย จะถูกลบไปด้วย และกู้คืนไม่ได้`
                  : "ตำแหน่งงานนี้ยังไม่มีผู้สมัคร ลบแล้วกู้คืนไม่ได้"}
              </p>
              <p>
                ถ้าเพียงต้องการหยุดรับใบสมัคร ให้เลือก{" "}
                <span className="font-semibold text-on-surface">ปิดรับสมัคร</span> แทน
                ข้อมูลจะยังอยู่ครบ
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
