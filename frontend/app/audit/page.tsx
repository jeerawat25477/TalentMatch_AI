"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import Breadcrumb from "@/components/breadcrumb";
import Spinner from "@/components/spinner";
import { STAGE_LABEL } from "@/components/board-card";
import { fetcher } from "@/lib/api";
import { EMPLOYEE_STATUS, INTERVIEW_RESULT } from "@/lib/types";
import type { AuditEntry, AuditOut, BoardStage, EmployeeStatus, InterviewResult } from "@/lib/types";
import { useIsAdmin, useMe } from "@/lib/use-me";

const RANGES = [
  { days: 1, label: "วันนี้" },
  { days: 7, label: "7 วันล่าสุด" },
  { days: 30, label: "30 วันล่าสุด" },
  { days: 365, label: "1 ปี" },
];

/** detail ที่ backend เก็บ (คีย์ที่อนุญาตเท่านั้น) → ข้อความสั้น ๆ */
function describe(e: AuditEntry): string {
  const d = e.detail;
  const parts: string[] = [];
  if (d.decision) parts.push(d.decision === "approved" ? "ผ่าน" : "ไม่ผ่าน");
  if (typeof d.count === "number") parts.push(`${d.count} คน`);
  if (d.status === "open") parts.push("เปิดรับสมัคร");
  else if (d.status === "closed") parts.push("ปิดรับสมัคร");
  else if (typeof d.status === "string" && d.status in EMPLOYEE_STATUS)
    parts.push(EMPLOYEE_STATUS[d.status as EmployeeStatus].label);
  if (typeof d.stage === "string") parts.push(STAGE_LABEL[d.stage as BoardStage] ?? d.stage);
  if (typeof d.result === "string")
    parts.push(INTERVIEW_RESULT[d.result as InterviewResult]?.label ?? d.result);
  if (d.response) parts.push(d.response === "accepted" ? "ตอบรับ" : "ปฏิเสธ");
  if (typeof d.enabled === "boolean") parts.push(d.enabled ? "เปิด" : "ปิด");
  if (d.to) parts.push(`ถึง ${d.to}`);
  if (d.name) parts.push(`"${d.name}"`);
  return parts.join(" · ");
}

function targetHref(e: AuditEntry): string | null {
  if (e.target_deleted || !e.target_id) return null;
  if (e.target_type === "candidate" && e.job_id) return `/jobs/${e.job_id}/candidates/${e.target_id}`;
  if (e.target_type === "job") return `/jobs/${e.target_id}`;
  if (e.target_type === "employee") return `/employees/${e.target_id}`;
  return null;
}

function targetText(e: AuditEntry): string | null {
  if (!e.target_type) return null;
  const kind = { job: "ตำแหน่ง", candidate: "ผู้สมัคร", employee: "พนักงาน", template: "เทมเพลต" }[e.target_type];
  if (e.target_deleted) return `${kind} (ลบแล้ว)`;
  return e.target_label ?? kind;
}

const OUTCOME: Record<AuditEntry["outcome"], { text: string; cls: string } | null> = {
  ok: null,
  denied: { text: "ถูกกัน", cls: "text-error" },
  failed: { text: "รหัสผิด", cls: "text-error" },
  error: { text: "ไม่สำเร็จ", cls: "text-on-surface-variant" },
};

const fmt = new Intl.DateTimeFormat("th-TH", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

/** ประวัติการใช้งาน — ใครทำอะไร เมื่อไร · admin เท่านั้น (backend ตอบ 403 ให้บัญชีอื่น) */
export default function AuditPage() {
  const me = useMe();
  const isAdmin = useIsAdmin();
  const [username, setUsername] = useState("");
  const [action, setAction] = useState("");
  const [days, setDays] = useState(7);

  const qs = new URLSearchParams({ days: String(days) });
  if (username) qs.set("username", username);
  if (action) qs.set("action", action);
  const { data, error, isLoading } = useSWR<AuditOut>(
    isAdmin ? `/api/v1/audit?${qs}` : null,
    fetcher,
    { refreshInterval: 30_000 },
  );

  if (me.data && !isAdmin) {
    return (
      <div className="glass-card rounded-2xl p-lg text-center space-y-sm max-w-lg mx-auto">
        <p className="text-headline-md text-on-surface">หน้านี้สำหรับผู้ดูแลระบบ</p>
        <p className="text-label-md text-on-surface-variant">บัญชีทดลองดูประวัติการใช้งานไม่ได้</p>
      </div>
    );
  }

  const selectCls =
    "bg-glass/60 border border-outline/30 rounded-lg px-sm py-xs text-label-md text-on-surface min-w-0";

  return (
    <div className="space-y-md">
      <Breadcrumb items={[{ label: "ประวัติการใช้งาน" }]} />
      <div>
        <h1 className="text-headline-lg text-on-surface">ประวัติการใช้งาน</h1>
        <p className="text-label-md text-on-surface-variant">
          ใครทำอะไร เมื่อไร · เก็บ 1 ปี · ไม่เก็บเงินเดือนหรือเนื้อหาอีเมล
        </p>
      </div>

      <div className="flex flex-wrap gap-xs">
        <select aria-label="กรองตามผู้ใช้" className={selectCls} value={username} onChange={(e) => setUsername(e.target.value)}>
          <option value="">ทุกคน</option>
          {data?.users.map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
        </select>
        <select aria-label="กรองตามการกระทำ" className={selectCls} value={action} onChange={(e) => setAction(e.target.value)}>
          <option value="">ทุกการกระทำ</option>
          {data?.actions.map((a) => (
            <option key={a.key} value={a.key}>
              {a.label}
            </option>
          ))}
        </select>
        <select aria-label="ช่วงเวลา" className={selectCls} value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {RANGES.map((r) => (
            <option key={r.days} value={r.days}>
              {r.label}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <p className="text-error text-label-md" role="alert">
          {error instanceof Error ? error.message : "โหลดไม่สำเร็จ"}
        </p>
      )}
      {(isLoading || !me.data) && (
        <p className="text-outline text-label-md flex items-center gap-xs">
          <Spinner className="text-[18px]" /> กำลังโหลด…
        </p>
      )}
      {data && data.items.length === 0 && (
        <p className="glass-card rounded-2xl p-md text-label-md text-on-surface-variant">ไม่มีรายการในช่วงนี้</p>
      )}

      {data && data.items.length > 0 && (
        <ul className="glass-card rounded-2xl divide-y divide-hairline">
          {data.items.map((e) => {
            const href = targetHref(e);
            const target = targetText(e);
            const extra = describe(e);
            const out = OUTCOME[e.outcome];
            const body = (
              <div className="flex items-start gap-sm px-md py-sm min-w-0">
                <time className="text-label-sm text-outline w-24 flex-none pt-0.5" dateTime={e.at}>
                  {fmt.format(new Date(e.at))}
                </time>
                <div className="min-w-0 flex-1">
                  <p className="text-label-md text-on-surface">
                    <span className="font-semibold">{e.username}</span> {e.label}
                    {extra && <span className="text-on-surface-variant"> · {extra}</span>}
                    {out && <span className={`font-semibold ${out.cls}`}> · ✕ {out.text}</span>}
                  </p>
                  {target && <p className="text-label-sm text-on-surface-variant truncate">{target}</p>}
                </div>
                {href && (
                  <span className="material-symbols-outlined text-[18px] text-outline flex-none" aria-hidden>
                    chevron_right
                  </span>
                )}
              </div>
            );
            return (
              <li key={e.id}>
                {href ? (
                  <Link href={href} className="block hover:bg-glass/30 transition-colors">
                    {body}
                  </Link>
                ) : (
                  body
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
