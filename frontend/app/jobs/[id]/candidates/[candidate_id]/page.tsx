"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import useSWR from "swr";
import AiInsight from "@/components/ai-insight";
import Breadcrumb from "@/components/breadcrumb";
import HireEmployeeDialog from "@/components/hire-employee-dialog";
import InterviewGuide from "@/components/interview-guide";
import RadarChart from "@/components/radar-chart";
import SkillGap from "@/components/skill-gap";
import StatusBadge from "@/components/status-badge";
import { fetcher, sendEmail, submitDecision } from "@/lib/api";
import { BANDS, initials, scoreBand } from "@/lib/types";
import type { CandidateDetail, Decision, Job } from "@/lib/types";

export default function CandidateDeepDive() {
  const { id, candidate_id } = useParams<{ id: string; candidate_id: string }>();
  const { data: c, mutate } = useSWR<CandidateDetail>(
    `/api/v1/candidates/${candidate_id}`,
    fetcher,
    { refreshInterval: 4000 },
  );
  // ใช้เฉพาะชื่อตำแหน่งใน breadcrumb (SWR แคชร่วมกับหน้า job dashboard)
  const { data: job } = useSWR<Job>(`/api/v1/jobs/${id}`, fetcher);

  const [notes, setNotes] = useState("");
  const [emailBody, setEmailBody] = useState("");
  const [emailSubject, setEmailSubject] = useState("");
  const [emailTo, setEmailTo] = useState("");
  const [busy, setBusy] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Decision | null>(null);
  // เปิดโหมดแก้ไขคำตัดสิน (กรณี HR กดผิด) — ปกติถ้าตัดสินแล้วจะโชว์สรุป ไม่โชว์ปุ่มคู่
  const [editing, setEditing] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [showHire, setShowHire] = useState(false);
  const router = useRouter();

  // ซิงก์ร่างอีเมลจาก backend เมื่อมีข้อมูลใหม่ (แก้ต่อในเครื่องได้)
  useEffect(() => {
    if (c?.email_draft?.body) setEmailBody(c.email_draft.body);
  }, [c?.email_draft?.body]);
  useEffect(() => {
    if (c?.email_draft?.subject) setEmailSubject(c.email_draft.subject);
  }, [c?.email_draft?.subject]);
  // ผู้รับดีฟอลต์จากอีเมลที่แกะได้ แต่ HR แก้ได้ก่อนส่ง (ด่านกัน spam relay)
  useEffect(() => {
    if (c?.email) setEmailTo(c.email);
  }, [c?.email]);

  async function handleSend() {
    setSending(true);
    setSendError(null);
    try {
      await sendEmail(candidate_id, {
        to: emailTo,
        subject: emailSubject,
        body: emailBody,
      });
      mutate(); // ดึง email_sent_at ล่าสุดมาแสดงป้าย "ส่งแล้ว"
    } catch (e) {
      setSendError(e instanceof Error ? e.message : "ส่งอีเมลไม่สำเร็จ");
    } finally {
      setSending(false);
    }
  }

  async function decide(decision: Decision) {
    setBusy(decision);
    setError(null);
    try {
      await submitDecision(candidate_id, decision, notes);
      setDone(decision);
      setEditing(false); // ตัดสินเสร็จ กลับไปโหมดสรุป
      mutate(); // กราฟจะ resume แล้วเติมคำถาม/อีเมล — poll เห็นเอง
    } catch (e) {
      setError(e instanceof Error ? e.message : "ส่งผลไม่สำเร็จ");
    } finally {
      setBusy(null);
    }
  }

  // ระหว่างโหลดก็ยังต้องเห็น breadcrumb — ตำแหน่งของหน้าห้ามหายไป
  if (!c)
    return (
      <div className="space-y-md">
        <Breadcrumb
          items={[
            { label: "ตำแหน่งงาน", href: "/" },
            { label: job?.title ?? "ผู้สมัคร", href: `/jobs/${id}` },
            { label: "รายงานเชิงลึก" },
          ]}
        />
        <p className="text-outline text-label-md">กำลังโหลด…</p>
      </div>
    );

  const band = BANDS[scoreBand(c.fit_score)];
  const profile = c.parsed_resume;

  return (
    <div className="space-y-md">
      <Breadcrumb
        items={[
          { label: "ตำแหน่งงาน", href: "/" },
          { label: job?.title ?? "ผู้สมัคร", href: `/jobs/${id}` },
          { label: c.full_name },
        ]}
      />

      {/* Profile + Gap analysis */}
      <div className="glass-card-elevated rounded-2xl overflow-hidden">
        <div className="p-md md:p-lg">
          <div className="flex flex-col md:flex-row gap-md">
            {/* ซ้าย: ข้อมูลผู้สมัคร */}
            <div className="w-full md:w-1/3 space-y-md">
              <div className="flex flex-col items-center text-center p-md rounded-xl bg-glass/40">
                <div className="relative mb-sm">
                  <div className="w-28 h-28 rounded-full border-4 border-tertiary-container p-1">
                    <div
                      className="w-full h-full rounded-full flex items-center justify-center text-headline-md font-semibold bg-primary-container text-on-primary"
                    >
                      {initials(c.full_name)}
                    </div>
                  </div>
                  <div
                    className="absolute -bottom-1 -right-1 px-3 py-1 rounded-full text-label-md font-semibold shadow-lg border-2 border-surface text-surface"
                    style={{ background: band.color }}
                  >
                    {c.fit_score ?? "—"}
                    {c.fit_score != null && "%"}
                  </div>
                </div>
                <h2 className="text-headline-md text-on-surface">{c.full_name}</h2>
                <div className="mt-1">
                  <StatusBadge score={c.fit_score} />
                </div>
              </div>

              <div className="space-y-xs">
                <InfoRow label="ประสบการณ์">
                  {profile ? `${profile.total_experience_years} ปี` : "—"}
                </InfoRow>
                <InfoRow label="การศึกษา">{profile?.education || "—"}</InfoRow>
                <InfoRow label="อีเมล">{c.email ?? "—"}</InfoRow>
              </div>

              {/* Bias Auditor */}
              {c.audit_log && (
                <div className="p-sm rounded-xl border border-secondary/20 bg-secondary-container/10 flex gap-xs items-start">
                  <span
                    className="material-symbols-outlined text-secondary"
                    style={{ fontVariationSettings: "'FILL' 1" }}
                  >
                    verified_user
                  </span>
                  <div>
                    <p className="text-on-secondary-fixed-variant text-label-md leading-snug">
                      {c.audit_log}
                    </p>
                    <p className="text-secondary font-bold text-label-sm mt-1">
                      {c.audit_status === "flagged"
                        ? "พบสัญญาณอคติ — ทบทวนอีกครั้ง"
                        : "ผ่านเกณฑ์ความโปร่งใส"}
                    </p>
                  </div>
                </div>
              )}
            </div>

            {/* ขวา: Gap Analysis */}
            <div className="flex-1 space-y-md">
              <div className="ai-glow-border p-md rounded-xl bg-glass/40">
                <h3 className="text-headline-md text-primary flex items-center gap-xs mb-xs">
                  <span className="material-symbols-outlined">query_stats</span>
                  Gap Analysis
                </h3>
                <RadarChart gap={c.gap_analysis} />
              </div>
              <SkillGap gap={c.gap_analysis} />
            </div>
          </div>
        </div>
      </div>

      {/* คำถามสัมภาษณ์ + ร่างอีเมล */}
      <div className="grid gap-md lg:grid-cols-2">
        <section className="glass-card rounded-2xl p-md">
          <h3 className="text-headline-md text-on-surface flex items-center gap-xs mb-sm">
            <span className="material-symbols-outlined text-primary">quiz</span>
            คำถามสัมภาษณ์
          </h3>
          <InterviewGuide plan={c.interview_plan} />
        </section>

        <section className="glass-card rounded-2xl p-md">
          <h3 className="text-headline-md text-on-surface flex items-center gap-xs mb-sm">
            <span className="material-symbols-outlined text-primary">mail</span>
            ร่างอีเมล
            {c.email_draft && (
              <span
                className={`text-label-sm px-2.5 py-1 rounded-full ${
                  c.email_draft.kind === "invitation"
                    ? "bg-secondary-container/40 text-on-secondary-container"
                    : "bg-error-container/60 text-on-error-container"
                }`}
              >
                {c.email_draft.kind === "invitation" ? "เชิญสัมภาษณ์" : "ปฏิเสธ"}
              </span>
            )}
          </h3>
          {c.email_draft ? (
            <div className="space-y-xs">
              {c.email_sent_at && (
                <div className="flex items-center gap-xs text-label-md text-secondary rounded-lg bg-secondary-container/20 px-sm py-xs">
                  <span
                    className="material-symbols-outlined text-[18px]"
                    style={{ fontVariationSettings: "'FILL' 1" }}
                  >
                    mark_email_read
                  </span>
                  <span>
                    {c.email_send_count > 0 && (
                      <span className="font-semibold">
                        ส่งแล้ว {c.email_send_count} ครั้ง ·{" "}
                      </span>
                    )}
                    ล่าสุดถึง {c.email_sent_to} เมื่อ{" "}
                    {new Date(c.email_sent_at).toLocaleString("th-TH")}
                  </span>
                </div>
              )}

              <label className="block text-label-sm text-outline">
                ผู้รับ
                <input
                  type="email"
                  value={emailTo}
                  onChange={(e) => setEmailTo(e.target.value)}
                  className="input-glass w-full mt-0.5"
                  placeholder="ตรวจอีเมลผู้รับก่อนส่ง"
                />
              </label>

              <label className="block text-label-sm text-outline">
                หัวข้อ
                <input
                  value={emailSubject}
                  onChange={(e) => setEmailSubject(e.target.value)}
                  className="input-glass w-full mt-0.5"
                />
              </label>

              <label className="block text-label-sm text-outline">
                เนื้อความ
                <textarea
                  value={emailBody}
                  onChange={(e) => setEmailBody(e.target.value)}
                  rows={8}
                  className="input-glass w-full resize-y mt-0.5"
                />
              </label>

              {sendError && (
                <p className="text-error text-label-md" role="alert">
                  {sendError}
                </p>
              )}

              <button
                onClick={() => {
                  if (c.email_sent_at && !confirm("อีเมลนี้เคยส่งไปแล้ว ยืนยันส่งซ้ำ?")) return;
                  handleSend();
                }}
                disabled={sending || !emailTo || !emailSubject || !emailBody}
                className="btn-primary w-full disabled:opacity-50"
              >
                <span className="material-symbols-outlined text-[18px]">send</span>
                {sending
                  ? "กำลังส่ง…"
                  : c.email_send_count > 0
                    ? `ส่งซ้ำ (ส่งแล้ว ${c.email_send_count} ครั้ง)`
                    : "ส่งอีเมล"}
              </button>
            </div>
          ) : (
            <p className="text-label-md text-outline">ยังไม่มีร่างอีเมล</p>
          )}
        </section>
      </div>

      {/* ผู้สมัครที่โปรไฟล์คล้ายกัน (RAG retrieval agent) — โชว์เฉพาะเมื่อมีผล */}
      {c.similar_candidates && c.similar_candidates.length > 0 && (
        <section className="glass-card rounded-2xl p-md">
          <h3 className="text-headline-md text-on-surface flex items-center gap-xs mb-sm">
            <span className="material-symbols-outlined text-primary">group</span>
            ผู้สมัครที่โปรไฟล์คล้ายกัน
            <span className="text-label-sm text-outline font-normal">
              (จากคลังผู้สมัครเก่า — ใช้เป็นบริบทเทียบเคียง)
            </span>
          </h3>
          <ul className="space-y-xs">
            {c.similar_candidates.map((s) => (
              <li
                key={s.id}
                className="flex items-center justify-between gap-sm p-sm rounded-lg bg-glass/30"
              >
                <div className="min-w-0">
                  <p className="text-label-md text-on-surface truncate">
                    {s.full_name ?? "—"}
                  </p>
                  <p className="text-label-sm text-outline truncate">
                    {s.job_title ?? "—"}
                  </p>
                </div>
                <div className="flex items-center gap-sm flex-none">
                  {s.fit_score != null && (
                    <span className="text-label-md text-on-surface-variant">
                      {s.fit_score}%
                    </span>
                  )}
                  {s.distance != null && (
                    <span className="text-label-sm text-outline">
                      ใกล้เคียง {Math.round((1 - s.distance) * 100)}%
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Human-in-the-Loop */}
      <div className="glass-card rounded-2xl p-md space-y-sm">
        <h3 className="text-headline-md text-on-surface">การตัดสินใจของ HR</h3>

        {/* บอกให้ชัดว่าการกดปุ่มจะทำอะไร — เดิมหน้านี้บอกว่า "กำลังสร้างผลลัพธ์ต่อ"
            ทุกกรณี ทั้งที่คนที่กราฟจบไปแล้วกดแล้วไม่มีอะไรเกิดขึ้นเลย
            ซ่อนเมื่อโชว์สรุปคำตัดสิน (โชว์เฉพาะตอนกำลังจะเลือก/แก้ไข) */}
        {(!(done ?? c.hr_decision) || editing) &&
          (c.graph_status === "awaiting_hr" ? (
          <p className="text-label-md text-on-surface-variant flex items-center gap-xs">
            <span className="material-symbols-outlined text-[18px] text-tertiary">
              hourglass_top
            </span>
            ระบบหยุดรอคำตัดสินของคุณอยู่ — คะแนนอยู่ในช่วงที่ต้องให้คนตัดสิน
          </p>
        ) : c.graph_status === "completed" ? (
          <p className="text-label-md text-on-surface-variant flex items-center gap-xs">
            <span className="material-symbols-outlined text-[18px] text-outline">
              history
            </span>
            ระบบตัดสินอัตโนมัติไปแล้ว — คำตัดสินของคุณจะ<b>ทับผลเดิม</b>
            และสร้างคำถาม/อีเมลใหม่
          </p>
        ) : (
          <p className="text-label-md text-outline flex items-center gap-xs">
            <span className="material-symbols-outlined text-[18px]">pending</span>
            กำลังประมวลผล — รอสักครู่ก่อนตัดสิน
          </p>
          ))}

        {(() => {
          // คำตัดสินที่มีผลจริง: ที่เพิ่งกดในหน้านี้ หรือที่บันทึกไว้ใน DB
          const decision = done ?? c.hr_decision;

          // ตัดสินแล้ว และไม่ได้อยู่ในโหมดแก้ไข → โชว์สรุป + ปุ่มแก้ไข
          if (decision && !editing) {
            const approved = decision === "approved";
            return (
              <div
                className={`flex items-center justify-between gap-sm flex-wrap rounded-xl px-md py-sm border-2 ${
                  approved
                    ? "bg-secondary-container/20 border-secondary/40"
                    : "bg-error-container/20 border-error/40"
                }`}
              >
                <div
                  className={`flex items-center gap-xs text-body-lg font-semibold ${
                    approved ? "text-secondary" : "text-error"
                  }`}
                >
                  <span
                    className="material-symbols-outlined text-[26px]"
                    style={{ fontVariationSettings: "'FILL' 1" }}
                  >
                    {approved ? "check_circle" : "cancel"}
                  </span>
                  {approved ? "อนุมัติให้สัมภาษณ์แล้ว" : "ปฏิเสธแล้ว"}
                </div>
                <button
                  onClick={() => {
                    setError(null);
                    setEditing(true);
                  }}
                  disabled={busy !== null}
                  className="btn-secondary-glass"
                >
                  <span className="material-symbols-outlined text-[18px]">edit</span>
                  แก้ไข
                </button>
              </div>
            );
          }

          // ยังไม่ตัดสิน หรือกำลังแก้ไข → โชว์ช่องบันทึก + ปุ่มคู่
          return (
            <>
              {editing && (
                <p className="text-label-md text-on-surface-variant flex items-center gap-xs">
                  <span className="material-symbols-outlined text-[18px] text-tertiary">
                    edit
                  </span>
                  กำลังแก้ไขคำตัดสิน — เลือกใหม่ด้านล่าง (จะทับผลเดิม)
                </p>
              )}
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="บันทึกเหตุผล (ไม่บังคับ) — จะถูกส่งเข้าไปในสถานะของกราฟด้วย"
                rows={2}
                className="input-glass w-full resize-y"
              />
              {error && <p className="text-error text-label-md">{error}</p>}
              <div className="flex flex-col md:flex-row gap-sm">
                <button
                  onClick={() => decide("approved")}
                  disabled={busy !== null}
                  className="flex-1 py-sm px-md bg-secondary text-on-secondary rounded-xl text-body-lg font-semibold flex items-center justify-center gap-xs hover:brightness-110 active:scale-95 duration-200 shadow-lg shadow-secondary/20 disabled:opacity-50"
                >
                  <span
                    className="material-symbols-outlined text-[26px]"
                    style={{ fontVariationSettings: "'FILL' 1" }}
                  >
                    check_circle
                  </span>
                  {busy === "approved" ? "กำลังส่ง…" : "อนุมัติให้สัมภาษณ์"}
                </button>
                <button
                  onClick={() => decide("rejected")}
                  disabled={busy !== null}
                  className="flex-1 py-sm px-md bg-glass/80 text-error border-2 border-error/50 rounded-xl text-body-lg font-semibold flex items-center justify-center gap-xs hover:bg-error/5 active:scale-95 duration-200 disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-[26px]">cancel</span>
                  {busy === "rejected" ? "กำลังส่ง…" : "ปฏิเสธ"}
                </button>
                {editing && (
                  <button
                    onClick={() => {
                      setError(null);
                      setEditing(false);
                    }}
                    disabled={busy !== null}
                    className="btn-secondary-glass md:w-auto justify-center"
                  >
                    ยกเลิก
                  </button>
                )}
              </div>
            </>
          );
        })()}
      </div>

      {/* รับเข้าเป็นพนักงาน — โผล่เมื่อไม่ใช่สายปฏิเสธ · ถ้าจ้างแล้วสลับเป็นลิงก์ไปทะเบียน */}
      {c.employee_id ? (
        <div className="glass-card rounded-2xl p-md flex items-center justify-between gap-sm flex-wrap">
          <div className="flex items-center gap-xs">
            <span
              className="material-symbols-outlined text-secondary"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              badge
            </span>
            <p className="text-label-md text-on-surface">
              ผู้สมัครรายนี้ถูกรับเข้าเป็นพนักงานแล้ว
            </p>
          </div>
          <Link href={`/employees/${c.employee_id}`} className="btn-tonal">
            ดูข้อมูลพนักงาน
            <span className="material-symbols-outlined text-[18px]">
              chevron_right
            </span>
          </Link>
        </div>
      ) : (
        c.email_draft?.kind !== "rejection" && (
          <div className="glass-card rounded-2xl p-md flex items-center justify-between gap-sm flex-wrap">
            <div>
              <h3 className="text-headline-md text-on-surface flex items-center gap-xs">
                <span className="material-symbols-outlined text-primary">badge</span>
                รับเข้าเป็นพนักงาน
              </h3>
              <p className="text-label-md text-on-surface-variant mt-0.5">
                สัมภาษณ์ผ่านแล้ว? บันทึกเข้าทะเบียนพนักงานเพื่อติดตามสถานะย้อนหลังได้
              </p>
            </div>
            <button
              onClick={() => setShowHire(true)}
              className="btn-primary text-body-md px-md py-sm rounded-xl shadow-lg shadow-primary/30 hover:-translate-y-0.5 transition-all"
            >
              <span
                className="material-symbols-outlined text-[22px]"
                style={{ fontVariationSettings: "'FILL' 1" }}
              >
                person_add
              </span>
              รับเข้าเป็นพนักงาน
            </button>
          </div>
        )
      )}

      {showHire && (
        <HireEmployeeDialog
          candidateId={candidate_id}
          defaultPosition={job?.title ?? ""}
          onHired={(employeeId) => router.push(`/employees/${employeeId}`)}
          onClose={() => setShowHire(false)}
        />
      )}

      {/* สรุปจากข้อมูลจริง */}
      {c.gap_analysis && (
        <AiInsight title="สรุปผลการประเมิน">
          ตรงตามทักษะที่ต้องมี{" "}
          {c.gap_analysis.matched_required.length}/
          {c.gap_analysis.matched_required.length +
            c.gap_analysis.missing_required.length}{" "}
          ข้อ และทักษะที่อยากได้ {c.gap_analysis.matched_preferred.length}/
          {c.gap_analysis.matched_preferred.length +
            c.gap_analysis.missing_preferred.length}{" "}
          ข้อ
          {c.gap_analysis.missing_required.length > 0 && (
            <> · ยังขาด: {c.gap_analysis.missing_required.join(", ")}</>
          )}
        </AiInsight>
      )}
    </div>
  );
}

function InfoRow({
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
