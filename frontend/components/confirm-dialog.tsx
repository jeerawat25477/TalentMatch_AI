"use client";

import { useEffect, useRef, useState } from "react";

/**
 * กล่องยืนยันการกระทำ — ใช้แทน window.confirm สำหรับงานที่ย้อนกลับไม่ได้.
 *
 * requireTypedText: บังคับให้พิมพ์ข้อความ (ชื่อตำแหน่งงาน) ให้ตรงก่อนกดยืนยันได้
 * ใช้เฉพาะการลบที่กวาดข้อมูลผู้สมัครไปด้วย — การกดพลาดครั้งเดียวต้องไม่ทำข้อมูลหาย
 */
export default function ConfirmDialog({
  title,
  body,
  confirmLabel,
  danger = false,
  requireTypedText,
  busy = false,
  error,
  onConfirm,
  onClose,
}: {
  title: string;
  body: React.ReactNode;
  confirmLabel: string;
  danger?: boolean;
  requireTypedText?: string;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  // ปิดด้วย Esc (แนวเดียวกับ drawer ใน app-shell) — แต่ห้ามปิดระหว่างยิง request
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  // โฟกัสเข้ากล่องทันทีที่เปิด เพื่อให้คีย์บอร์ดอยู่ในโมดัล ไม่ค้างที่หน้าเบื้องหลัง
  useEffect(() => {
    (inputRef.current ?? confirmRef.current)?.focus();
  }, []);

  const ready = !requireTypedText || typed.trim() === requireTypedText.trim();

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-md"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        className="absolute inset-0 bg-on-surface/30 backdrop-blur-sm"
        onClick={() => !busy && onClose()}
        aria-hidden
      />

      <div className="glass-card-elevated rounded-2xl p-md w-full max-w-md relative space-y-sm">
        <h2 className="text-body-lg font-semibold text-on-surface">{title}</h2>
        <div className="text-label-md text-on-surface-variant space-y-xs">
          {body}
        </div>

        {requireTypedText && (
          <label className="block space-y-xs">
            <span className="text-label-sm text-outline">
              พิมพ์ <span className="font-semibold text-on-surface">{requireTypedText}</span> เพื่อยืนยัน
            </span>
            <input
              ref={inputRef}
              className="input-glass w-full"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              disabled={busy}
              autoComplete="off"
            />
          </label>
        )}

        {error && (
          <p className="text-error text-label-md" role="alert">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-xs pt-xs">
          <button
            className="btn-secondary-glass"
            onClick={onClose}
            disabled={busy}
          >
            ยกเลิก
          </button>
          <button
            ref={confirmRef}
            className={danger ? "btn-danger" : "btn-tonal"}
            onClick={onConfirm}
            disabled={busy || !ready}
          >
            {busy ? "กำลังดำเนินการ…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
