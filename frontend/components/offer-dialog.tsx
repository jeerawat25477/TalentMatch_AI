"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { saveOffer } from "@/lib/api";
import { addDaysIso, localToday } from "@/lib/offer";
import type { JobOffer } from "@/lib/types";
import Spinner from "./spinner";

/**
 * โมดัลบันทึก/แก้ข้อเสนอจ้างงาน
 *
 * ในชีวิตจริง HR โทรยื่นข้อเสนอและต่อรองกันนอกระบบ แล้วส่ง Offer Letter ตามแบบฟอร์มของ
 * บริษัท — ที่นี่แค่ **จดไว้** ว่ายื่นอะไร ต้องตอบภายในเมื่อไหร่ พอผู้สมัครตอบรับ หน้าต่าง
 * รับเข้าเป็นพนักงานจะเติมค่าเหล่านี้ให้ · บันทึกแล้ว backend ย้ายขั้นเป็น "ยื่นข้อเสนอ" ให้เอง
 *
 * portal ไป <body> ด้วยเหตุผลเดียวกับโมดัลวันนัด (stacking context ของ app-shell)
 */
export default function OfferDialog({
  candidateId,
  candidateName,
  defaultPosition,
  existing,
  onSaved,
  onClose,
}: {
  candidateId: string;
  candidateName: string;
  /** ชื่อตำแหน่งงาน — ค่าตั้งต้นเมื่อยังไม่เคยยื่นข้อเสนอ */
  defaultPosition: string;
  existing: JobOffer | null;
  onSaved: () => void;
  onClose: () => void;
}) {
  const today = localToday();
  const [position, setPosition] = useState(existing?.position ?? defaultPosition);
  const [salary, setSalary] = useState(
    existing?.salary != null ? String(Number(existing.salary)) : "",
  );
  const [startDate, setStartDate] = useState(existing?.start_date ?? "");
  // ตอบภายใน 7 วันเป็นค่าตั้งต้นที่พบบ่อย HR แก้ได้
  const [respondBy, setRespondBy] = useState(existing?.respond_by ?? addDaysIso(today, 7));
  const [note, setNote] = useState(existing?.note ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // แก้ข้อเสนอหลังผู้สมัครตอบแล้ว = ข้อเสนอฉบับใหม่ คำตอบเดิมจะถูกล้าง — บอกก่อนกด
  const resetsAnswer = existing != null && existing.response !== "pending";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const salaryNum = salary.trim() ? Number(salary) : null;
  const salaryInvalid = salaryNum !== null && (!Number.isFinite(salaryNum) || salaryNum < 0);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await saveOffer(candidateId, {
        position: position.trim(),
        salary: salaryNum,
        start_date: startDate || null,
        respond_by: respondBy || null,
        note: note.trim() || null,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "บันทึกข้อเสนอไม่สำเร็จ");
      setBusy(false);
    }
  }

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-md"
      role="dialog"
      aria-modal="true"
      aria-label="ยื่นข้อเสนอ"
    >
      <div
        className="absolute inset-0 bg-on-surface/30 backdrop-blur-sm"
        onClick={() => !busy && onClose()}
        aria-hidden
      />
      <div className="glass-card-elevated rounded-2xl p-md w-full max-w-md relative space-y-sm max-h-[90vh] overflow-y-auto">
        <h2 className="text-headline-md text-on-surface">
          {existing ? "แก้ข้อเสนอ" : "ยื่นข้อเสนอ"}
        </h2>
        <p className="text-label-md text-on-surface-variant">
          {candidateName} — จดไว้ในระบบเท่านั้น ระบบไม่ส่งอีเมลหรือเอกสารถึงผู้สมัครให้เอง
        </p>

        {resetsAnswer && (
          <p
            role="note"
            className="text-label-md text-on-surface p-xs rounded-lg border border-tertiary/40 bg-tertiary-container/10"
          >
            ผู้สมัครตอบข้อเสนอเดิมไปแล้ว ถ้าบันทึก จะถือเป็นข้อเสนอใหม่และกลับไปรอคำตอบ
          </p>
        )}

        <label className="block space-y-xs">
          <span className="text-label-sm text-outline">ตำแหน่ง</span>
          <input
            className="input-glass w-full"
            value={position}
            onChange={(e) => setPosition(e.target.value)}
            maxLength={255}
            disabled={busy}
          />
        </label>

        <label className="block space-y-xs">
          <span className="text-label-sm text-outline">เงินเดือนที่เสนอ (บาท/เดือน)</span>
          <input
            type="number"
            inputMode="numeric"
            min={0}
            className="input-glass w-full"
            value={salary}
            onChange={(e) => setSalary(e.target.value)}
            placeholder="เช่น 45000"
            disabled={busy}
          />
        </label>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-sm">
          <label className="block space-y-xs">
            <span className="text-label-sm text-outline">วันเริ่มงาน</span>
            <input
              type="date"
              className="input-glass w-full"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              disabled={busy}
            />
          </label>
          <label className="block space-y-xs">
            <span className="text-label-sm text-outline">ผู้สมัครต้องตอบภายใน</span>
            <input
              type="date"
              className="input-glass w-full"
              value={respondBy}
              onChange={(e) => setRespondBy(e.target.value)}
              disabled={busy}
            />
          </label>
        </div>

        <label className="block space-y-xs">
          <span className="text-label-sm text-outline">หมายเหตุ (ไม่บังคับ)</span>
          <textarea
            rows={2}
            className="input-glass w-full resize-y"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="เช่น สวัสดิการเพิ่มเติม หรือผลการต่อรอง"
            maxLength={2000}
            disabled={busy}
          />
        </label>

        {salaryInvalid && (
          <p className="text-error text-label-md" role="alert">
            เงินเดือนต้องเป็นตัวเลขตั้งแต่ 0 ขึ้นไป
          </p>
        )}
        {error && (
          <p className="text-error text-label-md" role="alert">
            {error}
          </p>
        )}

        <div className="flex flex-wrap items-center justify-end gap-xs pt-xs">
          <button type="button" className="btn-secondary-glass" onClick={onClose} disabled={busy}>
            ปิด
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={save}
            disabled={busy || !position.trim() || salaryInvalid}
          >
            {busy && <Spinner className="text-[18px]" />}
            {busy ? "กำลังบันทึก…" : existing ? "บันทึกข้อเสนอ" : "ยื่นข้อเสนอ"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
