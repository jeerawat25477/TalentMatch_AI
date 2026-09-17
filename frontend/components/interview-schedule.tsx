"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
  googleCalendarUrl,
  interviewDetails,
  interviewTitle,
} from "@/lib/calendar-link";

/** วันเวลานัดแบบอ่านง่ายในภาษาไทย ตามเขตเวลาของเครื่อง HR */
export function formatSchedule(iso: string): string {
  return new Date(iso).toLocaleString("th-TH", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** ISO (มีโซน) → ค่าของ <input type="datetime-local"> ซึ่งต้องเป็นเวลาท้องถิ่นไม่มีโซน */
function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const off = d.getTimezoneOffset() * 60_000;
  return new Date(d.getTime() - off).toISOString().slice(0, 16);
}

/**
 * วันนัด + สถานที่ + ปุ่ม "เพิ่มลง Google Calendar" — ใช้ทั้งการ์ดบนกระดานและหน้ารายละเอียด
 *
 * ปุ่มเป็นลิงก์ธรรมดาเปิดแท็บใหม่ไปหน้าฟอร์มของ Google HR กดบันทึก event เองที่นั่น
 * ⚠️ ไม่รับอีเมลผู้สมัครเป็น prop เลยโดยตั้งใจ ลิงก์จึงไม่มีทางมีผู้เข้าร่วม
 * (ดูเหตุผลใน lib/calendar-link.ts)
 */
export function InterviewScheduleSummary({
  scheduledAt,
  location,
  candidateName,
  jobTitle,
  onEdit,
  compact = false,
}: {
  scheduledAt: string;
  location: string | null;
  candidateName: string;
  jobTitle: string | null | undefined;
  onEdit?: () => void;
  compact?: boolean;
}) {
  const href = googleCalendarUrl({
    title: interviewTitle(candidateName, jobTitle),
    start: scheduledAt,
    location,
    details: interviewDetails(candidateName, jobTitle, location),
  });

  return (
    <div
      className={`rounded-xl border border-outline-variant/40 bg-surface-container/40 flex items-start gap-xs ${
        compact ? "p-xs" : "p-sm"
      }`}
    >
      <span className="material-symbols-outlined text-primary text-[18px] flex-none mt-0.5">
        event
      </span>
      <div className="min-w-0 flex-1">
        <p className={`${compact ? "text-label-sm" : "text-label-md"} font-semibold text-on-surface`}>
          {formatSchedule(scheduledAt)}
        </p>
        {location && (
          <p className="text-label-sm text-on-surface-variant break-words">{location}</p>
        )}
      </div>
      <div className="flex items-center gap-0.5 flex-none">
        {onEdit && (
          <button
            type="button"
            onClick={onEdit}
            className="w-8 h-8 rounded-lg inline-flex items-center justify-center text-on-surface-variant hover:bg-primary-container/30"
            aria-label="แก้ไขวันนัด"
            title="แก้ไขวันนัด"
          >
            <span className="material-symbols-outlined text-[18px]">edit</span>
          </button>
        )}
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="w-8 h-8 rounded-lg inline-flex items-center justify-center text-primary hover:bg-primary-container/30"
          aria-label="เพิ่มลง Google Calendar (เปิดแท็บใหม่)"
          title="เพิ่มลง Google Calendar"
        >
          <span className="material-symbols-outlined text-[18px]">calendar_add_on</span>
        </a>
      </div>
    </div>
  );
}

/**
 * โมดัลกรอกวันนัด — เป็นโมดัล ไม่ใช่ช่องกรอกบนการ์ด เพราะการ์ดลากได้ (draggable):
 * กดค้างเพื่อเลือกข้อความในช่องกรอกจะกลายเป็นการลากการ์ดทั้งใบ
 *
 * portal ไป <body> ด้วยเหตุผลเดียวกับโมดัลผลสัมภาษณ์: เนื้อหาหน้าอยู่ใน stacking context
 * z-10 ของ app-shell แถบเมนู z-50 จะทับหัวโมดัลเสมอถ้า render ในที่
 */
export function InterviewScheduleDialog({
  candidateName,
  initialScheduledAt,
  initialLocation,
  onSave,
  onClose,
}: {
  candidateName: string;
  initialScheduledAt: string | null;
  initialLocation: string | null;
  /** ส่ง ISO ที่มีโซน (หรือ null = ล้างวันนัด) — โยน Error ได้ โมดัลจะแสดงข้อความเอง */
  onSave: (scheduledAt: string | null, location: string | null) => Promise<void>;
  onClose: () => void;
}) {
  const [when, setWhen] = useState(toLocalInput(initialScheduledAt));
  const [location, setLocation] = useState(initialLocation ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  async function save(clear = false) {
    setBusy(true);
    setError(null);
    try {
      // datetime-local ไม่มีโซน → new Date ตีความเป็นเวลาท้องถิ่นของเครื่อง HR แล้ว
      // toISOString แปลงเป็น UTC ที่มีโซน (backend ปฏิเสธเวลาที่ไม่มีโซน)
      await onSave(
        clear || !when ? null : new Date(when).toISOString(),
        clear ? null : location.trim() || null,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "บันทึกวันนัดไม่สำเร็จ");
      setBusy(false);
    }
  }

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-md"
      role="dialog"
      aria-modal="true"
      aria-label="นัดสัมภาษณ์"
    >
      <div
        className="absolute inset-0 bg-on-surface/30 backdrop-blur-sm"
        onClick={() => !busy && onClose()}
        aria-hidden
      />
      <div className="glass-card-elevated rounded-2xl p-md w-full max-w-md relative space-y-sm max-h-[90vh] overflow-y-auto">
        <h2 className="text-headline-md text-on-surface">นัดสัมภาษณ์</h2>
        <p className="text-label-md text-on-surface-variant">
          {candidateName} — บันทึกไว้ในระบบเท่านั้น ระบบไม่ส่งคำเชิญหรืออีเมลถึงผู้สมัครให้เอง
        </p>

        <label className="block space-y-xs">
          <span className="text-label-sm text-outline">วันและเวลา</span>
          <input
            type="datetime-local"
            className="input-glass w-full"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
            disabled={busy}
          />
        </label>

        <label className="block space-y-xs">
          <span className="text-label-sm text-outline">สถานที่หรือลิงก์ประชุม</span>
          <input
            className="input-glass w-full"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="เช่น ออนไลน์ Google Meet หรือ ห้องประชุม 3 ชั้น 5"
            maxLength={500}
            disabled={busy}
          />
        </label>

        {error && (
          <p className="text-error text-label-md" role="alert">
            {error}
          </p>
        )}

        <div className="flex flex-wrap items-center justify-end gap-xs pt-xs">
          {initialScheduledAt && (
            <button
              type="button"
              className="btn-secondary-glass me-auto"
              onClick={() => save(true)}
              disabled={busy}
            >
              ยกเลิกนัด
            </button>
          )}
          <button type="button" className="btn-secondary-glass" onClick={onClose} disabled={busy}>
            ปิด
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => save()}
            disabled={busy || !when}
          >
            {busy ? "กำลังบันทึก…" : "บันทึกวันนัด"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
