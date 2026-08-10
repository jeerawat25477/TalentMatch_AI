"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import Breadcrumb from "@/components/breadcrumb";
import ConfirmDialog from "@/components/confirm-dialog";
import { fetcher, setEmployeeStatus } from "@/lib/api";
import { EMPLOYEE_STATUS, initials } from "@/lib/types";
import type { EmployeeDetail, EmployeeStatus } from "@/lib/types";

// ปุ่มเปลี่ยนสถานะที่จะโชว์ (ยกเว้นสถานะปัจจุบัน) + ป้ายกำกับการกระทำ
const ACTIONS: Record<EmployeeStatus, { label: string; danger?: boolean }> = {
  permanent: { label: "บรรจุเป็นพนักงานประจำ" },
  probation: { label: "กลับเป็นทดลองงาน" },
  suspended: { label: "พักงานชั่วคราว" },
  terminated: { label: "ให้พ้นสภาพ", danger: true },
};

function fmtDate(d: string | null): string {
  return d ? new Date(d).toLocaleDateString("th-TH") : "—";
}

export default function EmployeeDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: e, mutate } = useSWR<EmployeeDetail>(
    `/api/v1/employees/${id}`,
    fetcher,
  );

  const [pending, setPending] = useState<EmployeeStatus | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function applyStatus() {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      await setEmployeeStatus(id, pending, note);
      setPending(null);
      setNote("");
      mutate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "เปลี่ยนสถานะไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  if (!e)
    return (
      <div className="space-y-md">
        <Breadcrumb
          items={[
            { label: "พนักงาน", href: "/employees" },
            { label: "รายละเอียด" },
          ]}
        />
        <p className="text-outline text-label-md">กำลังโหลด…</p>
      </div>
    );

  const s = EMPLOYEE_STATUS[e.status];
  const targets = (Object.keys(ACTIONS) as EmployeeStatus[]).filter(
    (k) => k !== e.status,
  );

  return (
    <div className="space-y-md">
      <Breadcrumb
        items={[
          { label: "พนักงาน", href: "/employees" },
          { label: e.full_name },
        ]}
      />

      {/* โปรไฟล์ */}
      <div className="glass-card-elevated rounded-2xl p-md md:p-lg">
        <div className="flex flex-col md:flex-row gap-md md:items-center">
          <div
            className="w-20 h-20 flex-none rounded-2xl flex items-center justify-center text-headline-md font-semibold text-white"
            style={{ background: "#0058be" }}
          >
            {initials(e.full_name)}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-xs flex-wrap">
              <h1 className="text-headline-lg text-on-surface">{e.full_name}</h1>
              <span
                className={`text-[11px] font-semibold px-2.5 py-1 rounded-full ${s.chip}`}
              >
                {s.label}
              </span>
            </div>
            <p className="text-body-md text-on-surface-variant">
              {e.position}
              {e.department && ` · ${e.department}`}
            </p>
            {e.email && (
              <p className="text-label-md text-outline">{e.email}</p>
            )}
          </div>
          {/* ลิงก์กลับไปดูประวัติ/ผลวิเคราะห์ผู้สมัคร */}
          {e.job_id && (
            <Link
              href={`/jobs/${e.job_id}/candidates/${e.candidate_id}`}
              className="btn-secondary-glass"
            >
              <span className="material-symbols-outlined text-[18px]">
                history
              </span>
              ดูประวัติผู้สมัคร
            </Link>
          )}
        </div>
      </div>

      {/* ข้อมูลการจ้างงาน */}
      <div className="glass-card rounded-2xl p-md">
        <h2 className="text-headline-md text-on-surface mb-sm">ข้อมูลการจ้างงาน</h2>
        <div className="grid gap-sm sm:grid-cols-2">
          <Info label="ตำแหน่ง">{e.position}</Info>
          <Info label="แผนก / ทีม">{e.department || "—"}</Info>
          <Info label="ตำแหน่งที่รับเข้า (JD)">{e.job_title || "—"}</Info>
          <Info label="เงินเดือน">
            {e.salary != null
              ? `${Number(e.salary).toLocaleString("th-TH")} บาท`
              : "—"}
          </Info>
          <Info label="วันเริ่มงาน">{fmtDate(e.start_date)}</Info>
          <Info label="วันครบทดลองงาน">{fmtDate(e.probation_end_date)}</Info>
          <Info label="รับเข้าเมื่อ">
            {new Date(e.hired_at).toLocaleDateString("th-TH")}
          </Info>
        </div>
      </div>

      {/* โน้ต HR */}
      {e.hr_notes && (
        <div className="glass-card rounded-2xl p-md">
          <h2 className="text-headline-md text-on-surface mb-xs">บันทึกจาก HR</h2>
          <p className="text-body-md text-on-surface-variant whitespace-pre-wrap">
            {e.hr_notes}
          </p>
        </div>
      )}

      {/* เปลี่ยนสถานะ */}
      <div className="glass-card rounded-2xl p-md space-y-sm">
        <h2 className="text-headline-md text-on-surface">เปลี่ยนสถานะ</h2>
        <p className="text-label-md text-on-surface-variant">
          สถานะปัจจุบัน: <span className="font-semibold">{s.label}</span>
        </p>
        <div className="flex gap-xs flex-wrap">
          {targets.map((t) => (
            <button
              key={t}
              onClick={() => {
                setError(null);
                setNote("");
                setPending(t);
              }}
              className={
                ACTIONS[t].danger
                  ? "btn-secondary-glass text-error border-error/50 hover:bg-error/5"
                  : "btn-secondary-glass"
              }
            >
              {ACTIONS[t].label}
            </button>
          ))}
        </div>
      </div>

      {pending && (
        <ConfirmDialog
          title={`${ACTIONS[pending].label}?`}
          danger={ACTIONS[pending].danger}
          confirmLabel="ยืนยัน"
          busy={busy}
          error={error}
          body={
            <div className="space-y-xs">
              <p>
                เปลี่ยนสถานะของ <b>{e.full_name}</b> จาก “{s.label}” เป็น “
                {EMPLOYEE_STATUS[pending].label}”
              </p>
              <label className="block space-y-xs">
                <span className="text-label-sm text-outline">
                  บันทึกเหตุผล (ไม่บังคับ — จะต่อท้ายลงบันทึก HR)
                </span>
                <textarea
                  className="input-glass w-full resize-y"
                  rows={2}
                  value={note}
                  onChange={(ev) => setNote(ev.target.value)}
                  disabled={busy}
                />
              </label>
            </div>
          }
          onConfirm={applyStatus}
          onClose={() => setPending(null)}
        />
      )}
    </div>
  );
}

function Info({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex justify-between items-center gap-sm p-sm rounded-lg bg-glass/30">
      <span className="text-outline text-label-md flex-none">{label}</span>
      <span className="text-on-surface text-label-md text-right break-words">
        {children}
      </span>
    </div>
  );
}
