"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import AiInsight from "@/components/ai-insight";
import Breadcrumb from "@/components/breadcrumb";
import EmailTemplatePicker from "@/components/email-template-picker";
import HireEmployeeDialog from "@/components/hire-employee-dialog";
import InterviewGuide from "@/components/interview-guide";
import InterviewOutcomeDialog from "@/components/interview-outcome-dialog";
import RadarChart from "@/components/radar-chart";
import SkillGap from "@/components/skill-gap";
import StatusBadge from "@/components/status-badge";
import { fetcher, searchCandidates, sendEmail, submitDecision } from "@/lib/api";
import {
  BANDS,
  CONFIDENCE,
  initials,
  INTERVIEW_RESULT,
  normalizeQuestions,
  QUEUE_STATE,
  scoreBand,
} from "@/lib/types";
import type {
  CandidateDetail,
  CandidateSearchHit,
  Decision,
  Job,
} from "@/lib/types";

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
  const [showOutcome, setShowOutcome] = useState(false);
  // ค้นหาผู้สมัครคล้ายกันแบบสั่งเอง — ยิงสดทุกครั้ง ไม่ได้บันทึกลง DB (hits = null คือยังไม่เคยค้น)
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [hits, setHits] = useState<CandidateSearchHit[] | null>(null);
  const seeded = useRef(false);
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

  // เติมคำค้นเริ่มต้นจากตำแหน่งงาน + ทักษะของผู้สมัคร — ทำครั้งเดียว เพราะ SWR poll ทุก 4 วิ
  // ถ้าเขียนทับทุกรอบจะลบสิ่งที่ HR กำลังพิมพ์อยู่ (parsed_resume ไม่มีฟิลด์ตำแหน่ง จึงยืม job.title)
  useEffect(() => {
    // รอทั้งสอง request ให้มาก่อน — ไม่งั้น c มาก่อน job แล้วจะ seed โดยไม่มีชื่อตำแหน่งติดไป
    if (seeded.current || !c || !job) return;
    const seed = [job.title, ...(c.parsed_resume?.skills ?? []).slice(0, 8)]
      .filter(Boolean)
      .join(", ");
    if (!seed) return;
    seeded.current = true;
    setQuery(seed);
  }, [c, job]);

  async function handleSearch() {
    setSearching(true);
    setSearchError(null);
    try {
      const found = await searchCandidates(query.trim(), 10);
      // endpoint สาธารณะไม่ได้ส่ง exclude_candidate_id (ต่างจาก retrieve_similar node)
      // จึงเจอตัวเองเป็นอันดับ 1 เสมอ ต้องกรองออกเอง
      setHits(found.filter((h) => h.id !== candidate_id));
    } catch (e) {
      setSearchError(e instanceof Error ? e.message : "ค้นหาไม่สำเร็จ");
      setHits(null);
    } finally {
      setSearching(false);
    }
  }

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
                <div className="mt-1 flex items-center justify-center gap-xs flex-wrap">
                  <StatusBadge score={c.fit_score} />
                  {/* ความมั่นใจของผลวิเคราะห์ — คนละมิติกับคะแนน แถวเก่าไม่มีก็ไม่โชว์ */}
                  {c.confidence && (
                    <span
                      title={CONFIDENCE[c.confidence].hint}
                      className={`inline-flex items-center gap-1 px-3 py-1 rounded-full text-label-sm font-bold whitespace-nowrap ${
                        CONFIDENCE[c.confidence].chip
                      }`}
                    >
                      <span className="material-symbols-outlined text-[14px]">
                        {CONFIDENCE[c.confidence].icon}
                      </span>
                      {CONFIDENCE[c.confidence].label}
                    </span>
                  )}
                </div>
                {/* ที่มาของคะแนนเป็นภาษาคน — แถวเก่าไม่มีค่านี้ ก็แค่ไม่โชว์ */}
                {c.score_explanation && (
                  <p className="mt-xs text-label-sm text-on-surface-variant leading-snug">
                    {c.score_explanation}
                  </p>
                )}
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
                    <p className="text-on-surface text-label-md leading-snug">
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

              {/* ลูป critique/revise: auditor ถอดเกณฑ์ที่มีอคติ แล้ว matcher คำนวณคะแนนใหม่ */}
              {c.bias_revision && (
                <div className="p-sm rounded-xl border border-tertiary/30 bg-tertiary-container/10 flex gap-xs items-start">
                  <span
                    className="material-symbols-outlined text-tertiary"
                    style={{ fontVariationSettings: "'FILL' 1" }}
                  >
                    autorenew
                  </span>
                  <div>
                    <p className="text-on-surface text-label-md leading-snug">
                      ตรวจอคติแล้วให้คำนวณคะแนนใหม่ {c.bias_revision.round} รอบ — ถอดเกณฑ์:{" "}
                      {[
                        ...c.bias_revision.excluded_required,
                        ...c.bias_revision.excluded_preferred,
                      ].join(", ") || "—"}
                    </p>
                    <p className="text-tertiary font-bold text-label-sm mt-1">
                      คะแนน {c.bias_revision.score_before ?? "—"} →{" "}
                      {c.bias_revision.score_after ?? c.fit_score ?? "—"}
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
              <SkillGap gap={c.gap_analysis} evidence={c.skill_evidence} />
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

          {/* บันทึกผลสัมภาษณ์จริง — โผล่เฉพาะคนที่มีคำถามให้ถาม (คนที่ถูกปฏิเสธไม่มีแผน
              สัมภาษณ์ ปุ่มนี้จึงไม่ควรมีอยู่ในสายตาเขา) */}
          {normalizeQuestions(c.interview_plan).length > 0 && (
            <div className="mt-sm pt-sm border-t border-outline-variant/40">
              {c.interview_outcome ? (
                <div className="space-y-xs">
                  <div className="flex items-center gap-base flex-wrap">
                    <span
                      className={`inline-flex items-center gap-1 text-label-sm font-semibold px-2.5 py-1 rounded-full ${
                        INTERVIEW_RESULT[c.interview_outcome.result].chip
                      }`}
                    >
                      <span className="material-symbols-outlined text-[15px]">
                        {INTERVIEW_RESULT[c.interview_outcome.result].icon}
                      </span>
                      {INTERVIEW_RESULT[c.interview_outcome.result].label}
                    </span>
                    <span className="text-label-sm text-on-surface-variant">
                      {c.interview_outcome.interviewed_at
                        ? `สัมภาษณ์ ${c.interview_outcome.interviewed_at}`
                        : "ไม่ได้ระบุวันที่"}
                      {" · "}
                      ให้คะแนน{" "}
                      {(c.interview_outcome.question_scores ?? []).filter(
                        (q) => q.score !== null,
                      ).length}{" "}
                      ข้อ
                    </span>
                    <button
                      className="btn-secondary-glass ms-auto text-label-sm py-1"
                      onClick={() => setShowOutcome(true)}
                    >
                      แก้ไขผล
                    </button>
                  </div>
                  {c.interview_outcome.overall_note && (
                    <p className="text-label-md text-on-surface-variant leading-relaxed">
                      {c.interview_outcome.overall_note}
                    </p>
                  )}
                </div>
              ) : (
                <div className="flex items-center gap-xs flex-wrap">
                  <button
                    className="btn-tonal"
                    onClick={() => setShowOutcome(true)}
                  >
                    <span className="material-symbols-outlined text-[18px]">
                      rate_review
                    </span>
                    บันทึกผลสัมภาษณ์
                  </button>
                  <p className="text-label-sm text-outline min-w-0 flex-1">
                    สัมภาษณ์เสร็จแล้วบันทึกผลไว้ที่นี่ — การ์ดบนกระดานจะย้ายไป
                    “สัมภาษณ์แล้ว” ให้เอง
                  </p>
                </div>
              )}
            </div>
          )}
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

              {/* เทมเพลตที่บันทึกไว้ — เติมช่องให้เฉย ๆ HR ยังต้องตรวจและกดส่งเอง */}
              <EmailTemplatePicker
                kind={c.email_draft.kind}
                subject={emailSubject}
                body={emailBody}
                vars={{
                  candidate_name: c.full_name,
                  job_title: job?.title ?? "",
                }}
                onApply={(s, b) => {
                  setEmailSubject(s);
                  setEmailBody(b);
                }}
              />

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

      {/* ค้นหาคล้ายกันแบบสั่งเอง (ad-hoc) — คนละที่มากับ section ด้านบน:
          อันบนมาจาก retrieve_similar node ตอนรันกราฟ บันทึกผูกกับผู้สมัครคนนี้ไว้แล้ว
          ส่วนอันนี้ยิง GET /candidates/search สดทุกครั้ง ไม่ persist */}
      <section className="glass-card rounded-2xl p-md">
        <h3 className="text-headline-md text-on-surface flex items-center gap-xs mb-xs">
          <span className="material-symbols-outlined text-primary">
            travel_explore
          </span>
          ค้นหาผู้สมัครคล้ายกันเพิ่มเติม
          <span className="text-label-sm text-outline font-normal">
            (ค้นสดจากคลังเวกเตอร์ — ไม่ได้บันทึกไว้)
          </span>
        </h3>
        <p className="text-label-sm text-outline mb-sm">
          แก้คำค้นได้ตามต้องการ — ค่าเริ่มต้นมาจากตำแหน่งงานและทักษะของผู้สมัครรายนี้
        </p>

        <div className="flex flex-col md:flex-row gap-xs">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && query.trim() && !searching) handleSearch();
            }}
            placeholder="เช่น Python, FastAPI, PostgreSQL"
            aria-label="คำค้นหาผู้สมัครคล้ายกัน"
            className="input-glass flex-1"
          />
          <button
            onClick={handleSearch}
            disabled={searching || !query.trim()}
            className="btn-primary md:w-auto justify-center disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[18px]">search</span>
            {searching ? "กำลังค้นหา…" : "ค้นหา"}
          </button>
        </div>

        {searchError && (
          <p className="text-error text-label-md mt-xs" role="alert">
            {searchError}
          </p>
        )}

        {hits !== null &&
          !searchError &&
          (hits.length === 0 ? (
            <p className="text-label-md text-outline mt-sm">
              ไม่พบผู้สมัครที่ใกล้เคียง — ลองแก้คำค้นให้กว้างขึ้น
            </p>
          ) : (
            <ul className="space-y-xs mt-sm">
              {hits.map((h) => {
                const row = (
                  <>
                    <div className="min-w-0">
                      <p className="text-label-md text-on-surface truncate">
                        {h.full_name}
                      </p>
                      <p className="text-label-sm text-outline truncate">
                        {h.job_title ?? "—"}
                      </p>
                    </div>
                    <div className="flex items-center gap-sm flex-none">
                      {h.fit_score != null && (
                        <span className="text-label-md text-on-surface-variant">
                          {h.fit_score}%
                        </span>
                      )}
                      {/* สูตรเดียวกับ section ด้านบน ตัวเลขจะได้อ่านเทียบกันได้ */}
                      <span className="text-label-sm text-outline">
                        ใกล้เคียง {Math.round((1 - h.distance) * 100)}%
                      </span>
                    </div>
                  </>
                );
                const cls =
                  "flex items-center justify-between gap-sm p-sm rounded-lg bg-glass/30";
                return (
                  <li key={h.id}>
                    {h.job_id ? (
                      <Link
                        href={`/jobs/${h.job_id}/candidates/${h.id}`}
                        className={`${cls} hover:bg-glass/60 transition-colors`}
                      >
                        {row}
                      </Link>
                    ) : (
                      <div className={cls}>{row}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          ))}
      </section>

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
        ) : c.queue_status === "deferred_quota" ? (
          /* โควตา AI วันนี้เต็ม — ต้องบอกให้ชัดว่าไม่ใช่ระบบพัง และไม่ต้องกดอะไร
             ไม่งั้น HR จะนั่งรอสิ่งที่ยังมาไม่ถึงจนกว่าโควตาจะรีเซ็ต */
          <p className="text-label-md text-on-surface-variant flex items-center gap-xs">
            <span className="material-symbols-outlined text-[18px] text-tertiary">
              hourglass_top
            </span>
            {QUEUE_STATE.deferred_quota.label} — ระบบจะวิเคราะห์ให้เองเมื่อโควตากลับมา
          </p>
        ) : (
          <p className="text-label-md text-outline flex items-center gap-xs">
            <span className="material-symbols-outlined text-[18px]">pending</span>
            {c.queue_status === "queued"
              ? "อยู่ในคิวรอประมวลผล — รอสักครู่ก่อนตัดสิน"
              : "กำลังประมวลผล — รอสักครู่ก่อนตัดสิน"}
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
                className={`rounded-xl px-md py-sm border-2 ${
                  approved
                    ? "bg-secondary-container/20 border-secondary/40"
                    : "bg-error-container/20 border-error/40"
                }`}
              >
                <div className="flex items-center justify-between gap-sm flex-wrap">
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
                      // เติมเหตุผลเดิมกลับเข้าช่อง — endpoint upsert ทับ notes ด้วยค่าที่ส่งมา
                      // เสมอ ถ้าปล่อยว่างแล้วกดยืนยัน เท่ากับลบเหตุผลเดิมทิ้ง
                      setNotes(c.hr_notes ?? "");
                      setEditing(true);
                    }}
                    disabled={busy !== null}
                    className="btn-secondary-glass"
                  >
                    <span className="material-symbols-outlined text-[18px]">edit</span>
                    แก้ไข
                  </button>
                </div>

                {/* บันทึก/เวลาที่ HR ตัดสิน — DB เก็บแถวเดียวต่อผู้สมัคร (upsert)
                    จึงเป็นคำตัดสินล่าสุด ไม่ใช่ประวัติย้อนหลัง */}
                {(c.hr_decided_at || c.hr_notes) && (
                  <div className="mt-xs pt-xs border-t border-outline-variant/30 space-y-1">
                    {c.hr_decided_at && (
                      <p className="text-label-sm text-outline flex items-center gap-xs">
                        <span className="material-symbols-outlined text-[16px]">
                          schedule
                        </span>
                        บันทึกล่าสุดเมื่อ{" "}
                        {new Date(c.hr_decided_at).toLocaleString("th-TH")}
                      </p>
                    )}
                    {c.hr_notes && (
                      <div className="flex items-start gap-xs">
                        <span className="material-symbols-outlined text-[16px] text-outline mt-0.5">
                          sticky_note_2
                        </span>
                        <p className="text-label-md text-on-surface whitespace-pre-wrap min-w-0">
                          {c.hr_notes}
                        </p>
                      </div>
                    )}
                  </div>
                )}
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

      {showOutcome && (
        <InterviewOutcomeDialog
          candidateId={candidate_id}
          plan={c.interview_plan}
          existing={c.interview_outcome}
          onSaved={() => {
            // อยู่หน้าเดิมโดยตั้งใจ ต่างจากการรับเข้าเป็นพนักงานที่พาไปหน้าพนักงาน —
            // HR มักบันทึกผลแล้วอ่านรายละเอียดของคนคนนั้นต่อ
            setShowOutcome(false);
            mutate();
          }}
          onClose={() => setShowOutcome(false)}
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
