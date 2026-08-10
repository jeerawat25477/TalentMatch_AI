"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import Breadcrumb from "@/components/breadcrumb";
import { fetcher } from "@/lib/api";
import { EMPLOYEE_STATUS, initials } from "@/lib/types";
import type { EmployeeListItem, EmployeeStatus } from "@/lib/types";

const AVATAR_COLORS = [
  "#0058be",
  "#2170e4",
  "#006c49",
  "#825100",
  "#427e9e",
  "#5a4fcf",
];

const TABS: { key: "all" | EmployeeStatus; label: string }[] = [
  { key: "all", label: "ทั้งหมด" },
  { key: "probation", label: EMPLOYEE_STATUS.probation.label },
  { key: "permanent", label: EMPLOYEE_STATUS.permanent.label },
  { key: "suspended", label: EMPLOYEE_STATUS.suspended.label },
  { key: "terminated", label: EMPLOYEE_STATUS.terminated.label },
];

export default function EmployeesPage() {
  const { data: employees, error, isLoading } = useSWR<EmployeeListItem[]>(
    "/api/v1/employees",
    fetcher,
  );
  const [tab, setTab] = useState<"all" | EmployeeStatus>("all");
  const [query, setQuery] = useState("");

  const list = employees ?? [];
  const q = query.trim().toLowerCase();
  const visible = list
    .filter((e) => tab === "all" || e.status === tab)
    .filter((e) => !q || e.full_name.toLowerCase().includes(q));

  const count = (s: EmployeeStatus) => list.filter((e) => e.status === s).length;

  return (
    <div className="space-y-md">
      <Breadcrumb items={[{ label: "พนักงาน" }]} />

      <div className="flex items-end justify-between flex-wrap gap-sm">
        <div>
          <p className="text-label-sm text-on-surface-variant uppercase tracking-wide">
            TalentMatch AI
          </p>
          <h1 className="text-headline-lg text-on-surface">พนักงาน</h1>
        </div>
        <div className="flex gap-md">
          <Stat label="ทั้งหมด" value={list.length} />
          <Stat
            label={EMPLOYEE_STATUS.probation.label}
            value={count("probation")}
            color="var(--band-review)"
          />
          <Stat
            label={EMPLOYEE_STATUS.permanent.label}
            value={count("permanent")}
            color="var(--band-pass)"
          />
        </div>
      </div>

      {error && (
        <p className="text-error text-label-md">
          โหลดรายชื่อพนักงานไม่สำเร็จ: {error.message}
        </p>
      )}
      {isLoading && <p className="text-outline text-label-md">กำลังโหลด…</p>}

      {employees && employees.length === 0 && (
        <div className="glass-card rounded-2xl p-lg text-center flex flex-col items-center gap-sm">
          <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center">
            <span className="material-symbols-outlined text-primary text-[28px]">
              badge
            </span>
          </div>
          <p className="text-on-surface-variant">
            ยังไม่มีพนักงาน — รับผู้สมัครที่สัมภาษณ์ผ่านเข้าเป็นพนักงานจากหน้ารายละเอียดผู้สมัคร
          </p>
        </div>
      )}

      {list.length > 0 && (
        <>
          {/* Controls */}
          <div className="flex items-center justify-between gap-sm flex-wrap">
            <div className="flex gap-base bg-glass/50 border border-outline/30 backdrop-blur-md p-1 rounded-xl flex-wrap">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={`px-sm py-1.5 rounded-lg text-label-md font-semibold transition-colors ${
                    tab === t.key
                      ? "bg-primary text-on-primary"
                      : "text-on-surface-variant hover:bg-glass/40"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="ค้นหาชื่อพนักงาน"
              className="input-glass flex-1 min-w-[220px] max-w-[320px] rounded-xl"
            />
          </div>

          <p className="text-label-sm text-outline">{visible.length} คน</p>

          <div className="flex flex-col gap-sm">
            {visible.map((e, i) => (
              <EmployeeRow key={e.id} employee={e} index={i} />
            ))}
            {visible.length === 0 && (
              <div className="text-center py-lg text-outline text-label-md">
                ไม่มีพนักงานที่ตรงกับตัวกรองนี้
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function EmployeeRow({
  employee,
  index,
}: {
  employee: EmployeeListItem;
  index: number;
}) {
  const s = EMPLOYEE_STATUS[employee.status];
  return (
    <Link
      href={`/employees/${employee.id}`}
      className="glass-card rounded-2xl px-md py-sm flex items-center gap-md flex-wrap hover:shadow-lg hover:-translate-y-0.5 transition-all"
    >
      <div
        className="w-12 h-12 flex-none rounded-xl flex items-center justify-center text-body-md font-semibold text-white"
        style={{ background: AVATAR_COLORS[index % AVATAR_COLORS.length] }}
      >
        {initials(employee.full_name)}
      </div>

      <div className="flex-[2] min-w-[180px]">
        <div className="text-body-md font-semibold text-on-surface mb-0.5">
          {employee.full_name}
        </div>
        <div className="text-label-md text-on-surface-variant">
          {employee.position}
          {employee.department && ` · ${employee.department}`}
        </div>
      </div>

      <div className="flex items-center gap-md ml-auto">
        {employee.start_date && (
          <div className="text-right hidden sm:block">
            <div className="text-label-sm text-outline">เริ่มงาน</div>
            <div className="text-label-md text-on-surface">
              {new Date(employee.start_date).toLocaleDateString("th-TH")}
            </div>
          </div>
        )}
        <span
          className={`text-[11px] font-semibold px-2.5 py-1 rounded-full ${s.chip}`}
        >
          {s.label}
        </span>
        <span className="material-symbols-outlined text-outline">
          chevron_right
        </span>
      </div>
    </Link>
  );
}

function Stat({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color?: string;
}) {
  return (
    <div className="text-center">
      <div
        className="text-headline-md font-semibold"
        style={color ? { color } : undefined}
      >
        {value}
      </div>
      <div className="text-label-sm text-outline">{label}</div>
    </div>
  );
}
