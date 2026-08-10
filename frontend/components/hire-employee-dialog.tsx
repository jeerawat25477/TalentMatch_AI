"use client";

import { useEffect, useState } from "react";
import { hireCandidate } from "@/lib/api";
import type { EmployeeCreate } from "@/lib/types";

// วันที่วันนี้ (YYYY-MM-DD) สำหรับ <input type="date">
function today(): string {
  return new Date().toISOString().slice(0, 10);
}
// +N วันจากวันเริ่มงาน — default วันครบทดลอง 90 วัน
function addDays(iso: string, days: number): string {
  const d = new Date(iso);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

/**
 * โมดัลกรอกข้อมูลตอนรับผู้สมัครเข้าเป็นพนักงาน.
 * position prefill จากชื่อตำแหน่งงาน; วันเริ่มงาน default วันนี้, วันครบทดลอง +90 วัน.
 * สำเร็จแล้วส่งต่อ employeeId ให้หน้าแม่ (พาไปหน้าพนักงาน).
 */
export default function HireEmployeeDialog({
  candidateId,
  defaultPosition,
  onHired,
  onClose,
}: {
  candidateId: string;
  defaultPosition: string;
  onHired: (employeeId: string) => void;
  onClose: () => void;
}) {
  const [position, setPosition] = useState(defaultPosition);
  const [department, setDepartment] = useState("");
  const [startDate, setStartDate] = useState(today());
  const [probationEnd, setProbationEnd] = useState(addDays(today(), 90));
  const [salary, setSalary] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ปิดด้วย Esc (แนวเดียวกับ ConfirmDialog) — ห้ามปิดระหว่างยิง request
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const payload: EmployeeCreate = {
        position: position.trim() || undefined,
        department: department.trim() || undefined,
        start_date: startDate || undefined,
        probation_end_date: probationEnd || undefined,
        salary: salary.trim() ? Number(salary) : undefined,
        hr_notes: notes.trim() || undefined,
      };
      const emp = await hireCandidate(candidateId, payload);
      onHired(emp.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "รับเข้าเป็นพนักงานไม่สำเร็จ");
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-md"
      role="dialog"
      aria-modal="true"
      aria-label="รับเข้าเป็นพนักงาน"
    >
      <div
        className="absolute inset-0 bg-on-surface/30 backdrop-blur-sm"
        onClick={() => !busy && onClose()}
        aria-hidden
      />

      <div className="glass-card-elevated rounded-2xl p-md w-full max-w-lg relative space-y-sm max-h-[90vh] overflow-y-auto">
        <h2 className="text-headline-md text-on-surface">รับเข้าเป็นพนักงาน</h2>
        <p className="text-label-md text-on-surface-variant">
          บันทึกข้อมูลการจ้างงาน — สถานะเริ่มต้นคือ “ทดลองงาน” ปรับภายหลังได้ในหน้าพนักงาน
        </p>

        <div className="grid gap-sm sm:grid-cols-2">
          <Field label="ตำแหน่ง">
            <input
              className="input-glass w-full"
              value={position}
              onChange={(e) => setPosition(e.target.value)}
              disabled={busy}
            />
          </Field>
          <Field label="แผนก / ทีม">
            <input
              className="input-glass w-full"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              placeholder="เช่น Engineering"
              disabled={busy}
            />
          </Field>
          <Field label="วันเริ่มงาน">
            <input
              type="date"
              className="input-glass w-full"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              disabled={busy}
            />
          </Field>
          <Field label="วันครบทดลองงาน">
            <input
              type="date"
              className="input-glass w-full"
              value={probationEnd}
              onChange={(e) => setProbationEnd(e.target.value)}
              disabled={busy}
            />
          </Field>
          <Field label="เงินเดือน (บาท)">
            <input
              type="number"
              min={0}
              step={500}
              className="input-glass w-full"
              value={salary}
              onChange={(e) => setSalary(e.target.value)}
              placeholder="ไม่บังคับ"
              disabled={busy}
            />
          </Field>
        </div>

        <Field label="โน้ต HR (ไม่บังคับ)">
          <textarea
            className="input-glass w-full resize-y"
            rows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            disabled={busy}
          />
        </Field>

        {error && (
          <p className="text-error text-label-md" role="alert">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-xs pt-xs">
          <button className="btn-secondary-glass" onClick={onClose} disabled={busy}>
            ยกเลิก
          </button>
          <button
            className="btn-primary"
            onClick={submit}
            disabled={busy || !position.trim()}
          >
            {busy ? "กำลังบันทึก…" : "ยืนยันรับเข้า"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-xs">
      <span className="text-label-sm text-outline">{label}</span>
      {children}
    </label>
  );
}
