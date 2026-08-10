"use client";

import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import Breadcrumb from "@/components/breadcrumb";
import JobActions from "@/components/job-actions";
import { fetcher } from "@/lib/api";
import { JOB_STATUS, type JobListItem } from "@/lib/types";

type Tab = "all" | "open" | "closed";

const TABS: { key: Tab; label: string }[] = [
  { key: "all", label: "ทั้งหมด" },
  { key: "open", label: "เปิดรับ" },
  { key: "closed", label: "ปิดแล้ว" },
];

export default function HomePage() {
  const { data: jobs, error, isLoading, mutate } = useSWR<JobListItem[]>(
    "/api/v1/jobs",
    fetcher,
  );
  const [tab, setTab] = useState<Tab>("all");
  const [actionError, setActionError] = useState<string | null>(null);

  // กรองฝั่ง client เพื่อให้ SWR มี cache key เดียว (ไม่ refetch ตอนสลับแท็บ)
  const counts = {
    all: jobs?.length ?? 0,
    open: jobs?.filter((j) => j.status === "open").length ?? 0,
    closed: jobs?.filter((j) => j.status === "closed").length ?? 0,
  };
  const visible = jobs?.filter((j) => tab === "all" || j.status === tab);

  return (
    <div className="space-y-md">
      <Breadcrumb items={[{ label: "ตำแหน่งงาน" }]} />

      <div className="flex items-end justify-between flex-wrap gap-sm">
        <div>
          <p className="text-label-sm text-on-surface-variant uppercase tracking-wide">
            TalentMatch AI
          </p>
          <h1 className="text-headline-lg text-on-surface">ตำแหน่งงาน</h1>
        </div>
        <Link
          href="/jobs/new"
          className="btn-primary text-body-md px-md py-sm rounded-xl shadow-lg shadow-primary/30 hover:shadow-primary/40 hover:-translate-y-0.5 transition-all"
        >
          <span className="material-symbols-outlined text-[22px]">add</span>
          สร้างตำแหน่งใหม่
        </Link>
      </div>

      {error && (
        <p className="text-error text-label-md">
          โหลดรายการงานไม่สำเร็จ: {error.message}
        </p>
      )}
      {actionError && (
        <p className="text-error text-label-md" role="alert">
          {actionError}
        </p>
      )}
      {isLoading && <p className="text-outline text-label-md">กำลังโหลด…</p>}

      {jobs && jobs.length > 0 && (
        <div className="flex gap-base bg-glass/50 border border-outline/30 backdrop-blur-md p-1 rounded-xl w-fit">
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
              {t.label} ({counts[t.key]})
            </button>
          ))}
        </div>
      )}

      {visible && visible.length === 0 && jobs && jobs.length > 0 && (
        <p className="text-outline text-label-md">
          ไม่มีตำแหน่งงานในหมวดนี้
        </p>
      )}

      {jobs && jobs.length === 0 && (
        <div className="glass-card rounded-2xl p-lg text-center flex flex-col items-center gap-sm">
          <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center">
            <span className="material-symbols-outlined text-primary text-[28px]">
              work
            </span>
          </div>
          <p className="text-on-surface-variant">
            ยังไม่มีตำแหน่งงาน — เริ่มต้นด้วยการสร้างตำแหน่งแรกของคุณ
          </p>
          <Link
            href="/jobs/new"
            className="btn-primary text-body-md px-md py-sm rounded-xl shadow-lg shadow-primary/30 hover:-translate-y-0.5 transition-all"
          >
            <span className="material-symbols-outlined text-[22px]">add</span>
            สร้างตำแหน่งใหม่
          </Link>
        </div>
      )}

      <div className="grid gap-md sm:grid-cols-2 lg:grid-cols-3">
        {visible?.map((job) => {
          const req = job.parsed_criteria?.required_skills ?? [];
          const closed = job.status === "closed";
          return (
            // เมนู ⋯ เป็น "พี่น้อง" ของ Link ไม่ใช่ลูก — ปุ่มซ้อนในลิงก์ผิดหลัก a11y
            <div key={job.id} className="relative">
              <Link
                href={`/jobs/${job.id}`}
                className={`glass-card rounded-2xl p-md hover:shadow-lg hover:-translate-y-0.5 transition-all block ${
                  closed ? "opacity-70" : ""
                }`}
              >
                <div className="flex items-start gap-xs mb-0.5 pr-8">
                  <h2 className="text-body-lg font-semibold text-on-surface line-clamp-1">
                    {job.title}
                  </h2>
                  {closed && (
                    <span
                      className={`shrink-0 text-[11px] font-semibold px-2 py-0.5 rounded-full ${JOB_STATUS.closed.chip}`}
                    >
                      {JOB_STATUS.closed.label}
                    </span>
                  )}
                </div>
                <p className="text-label-sm text-outline mb-sm">
                  {new Date(job.created_at).toLocaleDateString("th-TH")}
                </p>

                <div className="flex flex-wrap gap-base mb-sm min-h-[26px]">
                  {req.slice(0, 3).map((s) => (
                    <span
                      key={s}
                      className="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-primary-fixed text-on-primary-fixed-variant"
                    >
                      {s}
                    </span>
                  ))}
                </div>

                <div className="flex items-center gap-xs text-label-md pt-sm border-t border-hairline">
                  <span className="material-symbols-outlined text-primary text-[18px]">
                    group
                  </span>
                  <span className="text-primary font-bold">
                    {job.candidate_count}
                  </span>
                  <span className="text-outline">ผู้สมัคร</span>
                </div>
              </Link>

              <div className="absolute top-2 right-2">
                <JobActions
                  job={job}
                  onChanged={() => {
                    setActionError(null);
                    mutate();
                  }}
                  onError={setActionError}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
