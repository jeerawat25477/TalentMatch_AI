"use client";

import { useParams } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import AiInsight from "@/components/ai-insight";
import Breadcrumb from "@/components/breadcrumb";
import CandidateCard from "@/components/candidate-card";
import FileUpload from "@/components/file-upload";
import { fetcher } from "@/lib/api";
import { JOB_STATUS, scoreBand } from "@/lib/types";
import type { CandidateSummary, Job, ScoreBand } from "@/lib/types";

const TABS: { key: "all" | ScoreBand; label: string }[] = [
  { key: "all", label: "ทั้งหมด" },
  { key: "pass", label: "ผ่านเกณฑ์" },
  { key: "review", label: "Needs Review" },
  { key: "fail", label: "ไม่ผ่าน" },
];

export default function JobDashboard() {
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useState<"all" | ScoreBand>("all");
  const [query, setQuery] = useState("");

  const { data: job } = useSWR<Job>(`/api/v1/jobs/${id}`, fetcher);
  const { data: candidates, mutate } = useSWR<CandidateSummary[]>(
    `/api/v1/jobs/${id}/candidates`,
    fetcher,
    { refreshInterval: 4000 }, // poll: คะแนนทยอยขึ้นเมื่อ background task รันเสร็จ
  );

  const list = candidates ?? [];
  const scored = list.filter((c) => c.fit_score != null);
  const passed = list.filter((c) => scoreBand(c.fit_score) === "pass");
  const needsReview = list.filter((c) => scoreBand(c.fit_score) === "review");
  const top = scored.length > 0 ? scored[0] : null;

  const q = query.trim().toLowerCase();
  const visible = list
    .filter((c) => tab === "all" || scoreBand(c.fit_score) === tab)
    .filter((c) => !q || c.full_name.toLowerCase().includes(q));

  const criteria = job?.parsed_criteria;

  return (
    <div className="space-y-md">
      <Breadcrumb
        items={[
          { label: "ตำแหน่งงาน", href: "/" },
          { label: job?.title ?? "…" },
        ]}
      />

      {/* Header */}
      <div className="flex items-end justify-between flex-wrap gap-sm">
        <div>
          <p className="text-label-sm text-on-surface-variant uppercase tracking-wide">
            ผู้สมัคร
          </p>
          <div className="flex items-center gap-xs flex-wrap">
            <h1 className="text-headline-lg text-on-surface">{job?.title ?? "…"}</h1>
            {job?.status === "closed" && (
              <span
                className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${JOB_STATUS.closed.chip}`}
              >
                {JOB_STATUS.closed.label}
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-md">
          <Stat label="ทั้งหมด" value={list.length} />
          {/* ใช้ตัวแปรชุดเดียวกับ BANDS ไม่ให้สีแบนด์แตกเป็นสองชุด */}
          <Stat label="ผ่านเกณฑ์" value={passed.length} color="var(--band-pass)" />
          <Stat
            label="รอตัดสิน"
            value={needsReview.length}
            color="var(--band-review)"
          />
        </div>
      </div>

      {/* เกณฑ์จาก JD */}
      {criteria && (
        <div className="glass-card rounded-2xl p-md">
          <p className="text-label-sm text-outline mb-xs">
            เกณฑ์ที่ AI สกัดจาก JD (ประสบการณ์ขั้นต่ำ{" "}
            {criteria.min_experience_years} ปี)
          </p>
          <div className="flex flex-wrap gap-base">
            {criteria.required_skills?.map((s) => (
              <span
                key={s}
                className="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-primary-fixed text-on-primary-fixed-variant"
              >
                {s}
              </span>
            ))}
            {criteria.preferred_skills?.map((s) => (
              <span
                key={s}
                className="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-glass/60 border border-outline/40 text-on-surface-variant"
              >
                {s} (อยากได้)
              </span>
            ))}
          </div>
        </div>
      )}

      {/* AI insight — คำนวณจากข้อมูลจริงเท่านั้น */}
      {scored.length > 0 && (
        <AiInsight>
          วิเคราะห์แล้ว {scored.length} จาก {list.length} คน · ผ่านเกณฑ์{" "}
          {passed.length} คน
          {top && (
            <>
              {" "}
              — คะแนนสูงสุดคือ <strong>{top.full_name}</strong> ({top.fit_score})
            </>
          )}
          {needsReview.length > 0 && (
            <>
              {" "}
              · มี {needsReview.length} คนอยู่ในช่วงก้ำกึ่ง รอการตัดสินใจของคุณ
            </>
          )}
        </AiInsight>
      )}

      {/* Upload — ปิดรับสมัครแล้วอัปโหลดไม่ได้ (backend ตอบ 409 ด้วย) */}
      {job?.status === "closed" ? (
        <div className="glass-card rounded-2xl p-md flex items-center gap-xs">
          <span className="material-symbols-outlined text-on-surface-variant text-[20px]">
            lock
          </span>
          <p className="text-label-md text-on-surface-variant">
            ตำแหน่งนี้ปิดรับสมัครแล้ว — ข้อมูลผู้สมัครเดิมยังอยู่ครบ
            เปิดรับสมัครอีกครั้งได้จากเมนู ⋯ บนการ์ดในหน้าตำแหน่งงาน
          </p>
        </div>
      ) : (
        <FileUpload jobId={id} onUploaded={() => mutate()} />
      )}

      {/* Controls */}
      <div className="flex items-center justify-between gap-sm flex-wrap">
        <div className="flex gap-base bg-glass/50 border border-outline/30 backdrop-blur-md p-1 rounded-xl">
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
          placeholder="ค้นหาชื่อผู้สมัคร"
          className="input-glass flex-1 min-w-[220px] max-w-[320px] rounded-xl"
        />
      </div>

      <p className="text-label-sm text-outline">{visible.length} คน</p>

      {/* List */}
      <div className="flex flex-col gap-sm">
        {visible.map((c, i) => (
          <CandidateCard
            key={c.id}
            jobId={id}
            candidate={c}
            index={i}
            matched={[
              ...(c.gap_analysis?.matched_required ?? []),
              ...(c.gap_analysis?.matched_preferred ?? []),
            ]}
            missing={c.gap_analysis?.missing_required ?? []}
            onChanged={() => mutate()}
          />
        ))}
        {visible.length === 0 && (
          <div className="text-center py-lg text-outline text-label-md">
            {list.length === 0
              ? "ยังไม่มีผู้สมัคร — ลากไฟล์ PDF มาวางด้านบนเพื่อเริ่มวิเคราะห์"
              : "ไม่มีผู้สมัครที่ตรงกับตัวกรองนี้"}
          </div>
        )}
      </div>
    </div>
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
