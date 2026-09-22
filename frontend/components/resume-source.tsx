"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { getResumeFile } from "@/lib/api";

/**
 * ปุ่มดูเรซูเม่ — ให้ HR เทียบไฟล์จริงกับสิ่งที่ระบบอ่านได้ (ตัวอักษรไทยเพี้ยน ชื่อพิมพ์ผิด
 * ทักษะที่เทียบไม่เจอ) ว่าปัญหาอยู่ที่ไฟล์หรือที่ระบบ
 *
 * - "ดูเรซูเม่ต้นฉบับ" เฉพาะคนที่มีไฟล์ (เริ่มเก็บ 2026-09-22 — คนก่อนหน้านั้นไม่มีตลอดไป)
 *   fetch พร้อม JWT แล้วเปิด blob ในแท็บใหม่ ให้เบราว์เซอร์ใช้ตัวดู PDF ของมันเอง
 *   **ไม่ฝังลงในหน้าของเรา** เพราะไฟล์มาจากคนนอกและอาจฝังสคริปต์
 * - "ข้อความที่ระบบอ่านได้" มีทุกคน — raw_resume_text ที่ CandidateDetail ส่งมาอยู่แล้ว
 */
export default function ResumeSource({
  candidateId,
  candidateName,
  hasFile,
  text,
  photosHidden,
}: {
  candidateId: string;
  candidateName: string;
  hasFile: boolean;
  text: string | null;
  /** สวิตช์รูปหน้าคัดกรองปิดอยู่ — เตือนว่าไฟล์ต้นฉบับอาจมีรูป */
  photosHidden: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showText, setShowText] = useState(false);

  async function openPdf() {
    setError(null);
    // เปิดแท็บทันทีระหว่างที่ยังอยู่ในจังหวะคลิก ไม่งั้นเบราว์เซอร์บล็อกเป็นป๊อปอัป
    const tab = window.open("", "_blank");
    if (tab) tab.opener = null; // ตัดทางที่แท็บใหม่จะเอื้อมกลับมาแตะหน้านี้
    setBusy(true);
    try {
      const blob = await getResumeFile(candidateId);
      if (!blob) {
        tab?.close();
        setError("ไม่พบไฟล์ต้นฉบับ");
        return;
      }
      const url = URL.createObjectURL(blob);
      if (tab) tab.location.href = url;
      else window.open(url, "_blank", "noopener");
      // แท็บโหลดไฟล์ไปแล้ว คืนหน่วยความจำทีหลัง (คืนทันทีจะเปิดไม่ทัน)
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      tab?.close();
      setError(e instanceof Error ? e.message : "เปิดไฟล์ไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-xs">
        {hasFile && (
          <button
            type="button"
            onClick={openPdf}
            disabled={busy}
            className="btn-secondary-glass inline-flex items-center gap-1"
          >
            <span className="material-symbols-outlined text-[18px]" aria-hidden>
              picture_as_pdf
            </span>
            {busy ? "กำลังเปิด…" : "ดูเรซูเม่ต้นฉบับ"}
          </button>
        )}
        <button
          type="button"
          onClick={() => setShowText(true)}
          className="text-label-md text-primary hover:underline inline-flex items-center gap-0.5"
        >
          <span className="material-symbols-outlined text-[18px]" aria-hidden>
            article
          </span>
          ข้อความที่ระบบอ่านได้
        </button>
      </div>
      {hasFile && photosHidden && (
        <p className="text-label-sm text-outline">ไฟล์ต้นฉบับอาจมีรูปผู้สมัคร</p>
      )}
      {error && (
        <p className="text-error text-label-sm" role="alert">
          {error}
        </p>
      )}

      {showText && (
        <TextDialog
          name={candidateName}
          text={text}
          hasFile={hasFile}
          onClose={() => setShowText(false)}
        />
      )}
    </div>
  );
}

function TextDialog({
  name,
  text,
  hasFile,
  onClose,
}: {
  name: string;
  text: string | null;
  hasFile: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (typeof document === "undefined") return null;

  // portal ไป <body> ด้วยเหตุผลเดียวกับโมดัลอื่น (stacking context ของ app-shell)
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-md"
      role="dialog"
      aria-modal="true"
      aria-label="ข้อความที่ระบบอ่านได้"
    >
      <div
        className="absolute inset-0 bg-on-surface/30 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <div className="glass-card-elevated rounded-2xl p-md w-full max-w-2xl relative flex flex-col gap-sm max-h-[85vh]">
        <div>
          <h2 className="text-headline-md text-on-surface">ข้อความที่ระบบอ่านได้</h2>
          <p className="text-label-md text-on-surface-variant">
            {name} — {hasFile
              ? "เทียบกับไฟล์ต้นฉบับได้ ถ้าคำไหนเพี้ยน ปัญหาอยู่ที่การอ่านไฟล์"
              : "ไม่มีไฟล์ต้นฉบับ ผู้สมัครคนนี้เข้ามาก่อนระบบเริ่มเก็บไฟล์"}
          </p>
        </div>
        <pre className="flex-1 min-h-0 overflow-y-auto whitespace-pre-wrap break-words font-sans text-body-md text-on-surface p-sm rounded-xl bg-glass/40 border border-outline/20">
          {text?.trim() || "ไม่มีข้อความ"}
        </pre>
        <div className="flex justify-end">
          <button type="button" className="btn-secondary-glass" onClick={onClose}>
            ปิด
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
