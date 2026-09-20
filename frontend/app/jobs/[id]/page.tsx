"use client";

import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import useSWR from "swr";
import ApplyAddress from "@/components/apply-address";
import Breadcrumb from "@/components/breadcrumb";
import JobTabs from "@/components/job-tabs";
import CandidateCard from "@/components/candidate-card";
import ConfirmDialog from "@/components/confirm-dialog";
import CriteriaEditorDialog from "@/components/criteria-editor-dialog";
import FileUpload from "@/components/file-upload";
import PipelineFunnel from "@/components/pipeline-funnel";
import { bulkDecision, fetcher } from "@/lib/api";
import { JOB_STATUS, scoreBand } from "@/lib/types";
import { skillLabel } from "@/lib/skill-group";
import type {
  BulkDecisionResult,
  CandidateSummary,
  Decision,
  FunnelStage,
  Job,
  ScoreBand,
} from "@/lib/types";

/** เลือกตัดสินหมู่ได้เฉพาะคนที่กราฟหยุดรอ HR อยู่จริง — คนอื่น backend ข้ามอยู่ดี */
function isSelectable(c: CandidateSummary): boolean {
  return c.graph_status === "awaiting_hr" && !c.stalled;
}

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
  // เก็บเป็น "id" ไม่ใช่ index เพราะ SWR poll ทุก 4 วิแล้วลำดับการ์ดเลื่อนได้
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState<Decision | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [bulkResult, setBulkResult] = useState<BulkDecisionResult | null>(null);

  const { data: job, mutate: mutateJob } = useSWR<Job>(`/api/v1/jobs/${id}`, fetcher);
  const [editingCriteria, setEditingCriteria] = useState(false);
  // กรวยรวมทั้งตำแหน่ง — อ่านอย่างเดียว นับจากข้อมูลชุดเดียวกับกระดาน
  const { data: funnel } = useSWR<FunnelStage[]>(
    `/api/v1/jobs/${id}/funnel`,
    fetcher,
    { refreshInterval: 4000 },
  );
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

  // เลือกได้เฉพาะคนที่มองเห็นอยู่ตอนนี้ (หลังกรอง tab/ค้นหา) ไม่ใช่ทั้งตำแหน่ง
  const selectable = visible.filter(isSelectable);
  // ตัดคนที่หลุดเงื่อนไขไปแล้วออกทุกรอบ poll — ไม่งั้นจะส่ง id ที่ตัดสินไปแล้วซ้ำ
  const selectedIds = useMemo(
    () => selectable.filter((c) => picked.has(c.id)).map((c) => c.id),
    [selectable, picked],
  );
  const allPicked = selectable.length > 0 && selectedIds.length === selectable.length;

  function toggle(cid: string, on: boolean) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(cid);
      else next.delete(cid);
      return next;
    });
  }

  async function runBulk(decision: Decision) {
    setBulkBusy(true);
    setBulkError(null);
    try {
      const res = await bulkDecision(selectedIds, decision);
      setBulkResult(res);
      setPicked(new Set());
      setConfirming(null);
      mutate();
    } catch (e) {
      setBulkError(e instanceof Error ? e.message : "ตัดสินไม่สำเร็จ");
    } finally {
      setBulkBusy(false);
    }
  }

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

      {/* สลับมุมมอง — กระดานไม่ได้มาแทนหน้านี้ คนที่ยังรอตัดสิน/กำลังวิเคราะห์/ค้าง
          อยู่ในหน้านี้เท่านั้น ไม่ขึ้นกระดาน */}
      <JobTabs jobId={id} />

      {/* เกณฑ์จาก JD — แสดงแม้ AI อ่านไม่สำเร็จตอนสร้าง (criteria เป็น null) ไม่งั้น HR ไม่มีทางแก้ */}
      {job && (
        <div className="glass-card rounded-2xl p-md">
          <div className="flex items-start justify-between gap-xs flex-wrap mb-xs">
            <div>
              <p className="text-label-md font-semibold text-on-surface">
                ทักษะที่ใช้ให้คะแนนผู้สมัคร
              </p>
              <p className="text-label-sm text-on-surface-variant">
                {!criteria
                  ? "ยังไม่มีเกณฑ์ — AI อ่านประกาศไม่สำเร็จตอนสร้างตำแหน่ง กด “แก้ไขเกณฑ์” เพื่อกรอกเองหรือให้ AI อ่านใหม่"
                  : job.criteria_edited_at
                    ? `HR ตรวจและแก้แล้ว เมื่อ ${new Date(job.criteria_edited_at).toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short" })}`
                    : "AI อ่านจากประกาศงาน ยังไม่มีคนตรวจ — ควรตรวจก่อนเชื่อคะแนน"}
                {criteria && " · "}
                {criteria &&
                  ((criteria.min_experience_years ?? 0) > 0
                    ? `ต้องมีประสบการณ์อย่างน้อย ${criteria.min_experience_years} ปี`
                    : "ประกาศไม่ได้กำหนดประสบการณ์")}
              </p>
            </div>
            <button
              type="button"
              className="btn-tonal text-label-sm py-1"
              onClick={() => setEditingCriteria(true)}
            >
              <span className="material-symbols-outlined text-[16px]">edit</span>
              แก้ไขเกณฑ์
            </button>
          </div>
          {job.criteria_warnings?.map((w) => (
            <div
              key={w}
              role="note"
              className="flex gap-base items-start p-xs mb-xs rounded-lg border border-tertiary/40 bg-tertiary-container/10"
            >
              <span
                className="material-symbols-outlined text-tertiary text-[18px] flex-none"
                style={{ fontVariationSettings: "'FILL' 1" }}
              >
                warning
              </span>
              <p className="text-label-md text-on-surface">
                {w} · กด &ldquo;แก้ไขเกณฑ์&rdquo; เพื่อตรวจ
              </p>
            </div>
          ))}
          <div className="flex flex-wrap gap-base">
            {criteria?.required_skills?.map((s) => (
              <span
                key={s}
                className="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-primary-fixed text-on-primary-fixed-variant"
              >
                {skillLabel(s)}
              </span>
            ))}
            {criteria?.preferred_skills?.map((s) => (
              <span
                key={s}
                className="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-glass/60 border border-outline/40 text-on-surface-variant"
              >
                {skillLabel(s)} (อยากได้)
              </span>
            ))}
          </div>
        </div>
      )}

      {editingCriteria && job && (
        <CriteriaEditorDialog
          job={job}
          onSaved={(r) => {
            // เอาผลจาก backend ใส่ cache ทันที แล้วดึงรายชื่อใหม่ให้คะแนนเปลี่ยนตามโดยไม่รอรอบ poll
            mutateJob(r.job, false);
            mutate();
            setEditingCriteria(false);
          }}
          onClose={() => setEditingCriteria(false)}
          onReanalyzed={() => mutateJob()}
        />
      )}

      {/* กรวย + สรุปหนึ่งบรรทัดในใบเดียวกัน — เดิมสรุปเป็นแถบแยกใต้กรวย แล้วพูดซ้ำกับทั้ง
          ตัวเลขบนหัวหน้า (ผ่านเกณฑ์ / รอตัดสิน) และกรวยเอง · เหลือเฉพาะสองอย่างที่ไม่มีที่อื่น
          คือความคืบหน้าการวิเคราะห์ กับคนคะแนนสูงสุด */}
      {funnel && (
        <PipelineFunnel
          stages={funnel}
          note={
            scored.length > 0 ? (
              <>
                วิเคราะห์แล้ว {scored.length} จาก {list.length} คน
                {top && (
                  <>
                    {" · "}คะแนนสูงสุดคือ <strong>{top.full_name}</strong> ({top.fit_score})
                  </>
                )}
              </>
            ) : undefined
          }
        />
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

      {/* ทางเข้าที่สองของเรซูเม่ — โผล่เฉพาะเมื่อปากทางรับอีเมลเปิดอยู่จริง
          (คอมโพเนนต์ซ่อนตัวเองเมื่อปิด/ยังไม่ตั้งค่า/งานปิดรับ) */}
      <ApplyAddress jobId={id} jobOpen={job?.status !== "closed"} />

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

      {/* แถบตัดสินหมู่ — โผล่เมื่อเลือกอย่างน้อย 1 คน */}
      {selectedIds.length > 0 && (
        <div className="glass-card-elevated rounded-xl px-md py-sm flex items-center gap-sm flex-wrap sticky top-2 z-20">
          <span className="text-label-md text-on-surface font-semibold">
            เลือกไว้ {selectedIds.length} คน
          </span>
          <div className="flex-1" />
          <button
            onClick={() => setConfirming("approved")}
            className="btn-primary"
            disabled={bulkBusy}
          >
            <span className="material-symbols-outlined text-[18px]">check_circle</span>
            อนุมัติทั้งหมด ({selectedIds.length})
          </button>
          <button
            onClick={() => setConfirming("rejected")}
            className="btn-danger"
            disabled={bulkBusy}
          >
            <span className="material-symbols-outlined text-[18px]">cancel</span>
            ปฏิเสธทั้งหมด ({selectedIds.length})
          </button>
          <button
            onClick={() => setPicked(new Set())}
            className="btn-secondary-glass"
            disabled={bulkBusy}
          >
            ล้างการเลือก
          </button>
        </div>
      )}

      {/* สรุปผลการรับเข้าคิว — ผลรายคนจะทยอยขึ้นเองจากการ poll */}
      {bulkResult && (
        <div className="p-sm rounded-xl border border-secondary/30 bg-secondary-container/10 flex gap-xs items-start">
          <span className="material-symbols-outlined text-secondary text-[20px]">
            playlist_add_check
          </span>
          <div className="flex-1 text-on-surface text-label-md leading-snug">
            รับเข้าคิวแล้ว {bulkResult.accepted} คน — ผลจะทยอยขึ้นในรายชื่อด้านล่าง
            {bulkResult.skipped.length > 0 && (
              <ul className="mt-1 space-y-0.5 text-on-surface-variant text-label-sm">
                {bulkResult.skipped.map((sk) => (
                  <li key={sk.id}>
                    ข้าม{" "}
                    {list.find((c) => c.id === sk.id)?.full_name ?? sk.id.slice(0, 8)} —{" "}
                    {sk.reason}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button
            onClick={() => setBulkResult(null)}
            aria-label="ปิดสรุปผล"
            className="material-symbols-outlined text-outline text-[18px] flex-none"
          >
            close
          </button>
        </div>
      )}

      <div className="flex items-center gap-sm flex-wrap">
        <p className="text-label-sm text-outline">{visible.length} คน</p>
        {selectable.length > 0 && (
          <label className="flex items-center gap-xs text-label-sm text-on-surface-variant cursor-pointer">
            <input
              type="checkbox"
              checked={allPicked}
              onChange={(e) =>
                setPicked(
                  e.target.checked ? new Set(selectable.map((c) => c.id)) : new Set(),
                )
              }
              className="w-4 h-4 accent-primary cursor-pointer"
            />
            เลือกทั้งหมดที่รอตัดสิน ({selectable.length})
          </label>
        )}
      </div>

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
            selectable={isSelectable(c)}
            selected={picked.has(c.id)}
            onSelectChange={(on) => toggle(c.id, on)}
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

      {confirming && (
        <ConfirmDialog
          title={
            confirming === "approved"
              ? "อนุมัติหลายคนพร้อมกัน"
              : "ปฏิเสธหลายคนพร้อมกัน"
          }
          danger={confirming === "rejected"}
          confirmLabel={
            confirming === "approved" ? "อนุมัติทั้งหมด" : "ปฏิเสธทั้งหมด"
          }
          busy={bulkBusy}
          error={bulkError}
          onClose={() => {
            setConfirming(null);
            setBulkError(null);
          }}
          onConfirm={() => runBulk(confirming)}
          body={
            <>
              <p>
                จะ{confirming === "approved" ? "อนุมัติ" : "ปฏิเสธ"}ผู้สมัคร{" "}
                <b>{selectedIds.length} คน</b> พร้อมกัน ระบบจะสร้าง
                {confirming === "approved" ? "คำถามสัมภาษณ์และ" : ""}ร่างอีเมลให้แต่ละคน
              </p>
              {/* เตือนโควตา: อนุมัติ 1 คน = ~2 LLM call (planner+drafter) จากโควตาฟรี 20/วัน */}
              <p className="mt-xs text-on-surface-variant">
                ใช้โควตา AI ประมาณ{" "}
                <b>
                  {selectedIds.length * (confirming === "approved" ? 2 : 1)} ครั้ง
                </b>{" "}
                จากโควตาฟรีวันละ 20 ครั้ง
              </p>
              <p className="mt-xs text-on-surface-variant">
                ยังไม่มีอีเมลถูกส่งออกไป — ต้องเปิดหน้าของแต่ละคนแล้วกดส่งเองเหมือนเดิม
              </p>
            </>
          }
        />
      )}
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
