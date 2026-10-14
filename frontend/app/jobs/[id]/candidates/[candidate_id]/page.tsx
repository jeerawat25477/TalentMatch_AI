"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import Breadcrumb from "@/components/breadcrumb";
import CandidateAvatar, { useScreeningPhotos } from "@/components/candidate-avatar";
import CandidateTimeline from "@/components/candidate-timeline";
import ConfirmDialog from "@/components/confirm-dialog";
import EmailTemplatePicker from "@/components/email-template-picker";
import HireEmployeeDialog from "@/components/hire-employee-dialog";
import HireOrCloseCard from "@/components/hire-or-close-card";
import InterviewGuide from "@/components/interview-guide";
import {
  formatSchedule,
  InterviewScheduleDialog,
  InterviewScheduleSummary,
} from "@/components/interview-schedule";
import InterviewOutcomeDialog from "@/components/interview-outcome-dialog";
import RadarChart from "@/components/radar-chart";
import ScoreBreakdown from "@/components/score-breakdown";
import { CandidateBiasBox } from "@/components/bias-ack";
import ScoreHistogram from "@/components/score-histogram";
import ResumeSource from "@/components/resume-source";
import SkillGap from "@/components/skill-gap";
import StatusBadge from "@/components/status-badge";
import WorkingNote from "@/components/working-note";
import Spinner from "@/components/spinner";
import NotFoundCard, { isNotFound, useGone } from "@/components/not-found-card";
import {
  biasWarningOf,
  clearEmailDraft,
  fetcher,
  resumeCandidate,
  searchCandidates,
  saveEmailDraft,
  sendEmail,
  setStage,
  submitDecision,
} from "@/lib/api";
import {
  appendScheduleLine,
  BANDS,
  CONFIDENCE,
  DEFAULT_REJECTION,
  emailMode,
  fillTemplate,
  INTERVIEW_RESULT,
  normalizeQuestions,
  QUEUE_STATE,
  scheduleLine,
  scoreBand,
} from "@/lib/types";
import type {
  BiasPhrase,
  CandidateDetail,
  CandidateSearchHit,
  Decision,
  SamePerson,
  Job,
  ScoreDistribution,
} from "@/lib/types";

export default function CandidateDeepDive() {
  const { id, candidate_id } = useParams<{ id: string; candidate_id: string }>();
  const { gone, swr: goneSwr } = useGone();
  const { data: c, mutate } = useSWR<CandidateDetail>(
    `/api/v1/candidates/${candidate_id}`,
    fetcher,
    { ...goneSwr, refreshInterval: gone ? 0 : 4000 }, // ถูกลบ = หยุด poll
  );
  // ใช้เฉพาะชื่อตำแหน่งใน breadcrumb (SWR แคชร่วมกับหน้า job dashboard) · บอกปุ่มกลับว่ายังมีตำแหน่งไหม
  const { data: job } = useSWR<Job>(`/api/v1/jobs/${id}`, fetcher, {
    shouldRetryOnError: (e: Error) => !isNotFound(e),
  });
  const showPhoto = useScreeningPhotos();
  // ขอเฉพาะเมื่อคนนี้มีคะแนนแล้ว — ยังไม่มีผล ไม่มีหมุดให้ปัก จึงไม่แสดงกราฟนี้เลย
  const { data: distribution } = useSWR<ScoreDistribution>(
    c?.fit_score != null ? `/api/v1/jobs/${id}/score-distribution` : null,
    fetcher,
  );

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
  // ถ้อยคำที่ backend เตือนตอนกดส่ง — มีค่า = เปิดหน้าต่างให้ HR เลือกกลับไปแก้หรือส่งต่อ
  const [biasWarning, setBiasWarning] = useState<BiasPhrase[] | null>(null);
  const [showHire, setShowHire] = useState(false);
  const [showSchedule, setShowSchedule] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  // ชนิดของข้อความที่อยู่ในช่องตอนนี้ ถ้า HR เปลี่ยนเนื้อหาเป็นอีกแบบ (เลือกเทมเพลต /
  // ใช้ร่างปฏิเสธ) แต่ยังไม่บันทึก · null = ตรงกับร่างที่บันทึกไว้
  const [textKind, setTextKind] = useState<"invitation" | "rejection" | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [showOutcome, setShowOutcome] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);
  // ค้นหาผู้สมัครคล้ายกันแบบสั่งเอง — ยิงสดทุกครั้ง ไม่ได้บันทึกลง DB (hits = null คือยังไม่เคยค้น)
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [hits, setHits] = useState<CandidateSearchHit[] | null>(null);
  const seeded = useRef(false);
  // เก็บสถานะ "ยังไม่บันทึก" ไว้ใน ref เพราะ effect เตือนก่อนปิดแท็บถูกประกาศก่อนจุดที่
  // คำนวณค่านั้นได้ (ต้องอยู่เหนือ early return ตามกฎ hooks)
  const unsavedRef = useRef(false);
  const router = useRouter();

  // ซิงก์ร่างอีเมลจาก backend — **ฉบับที่ HR บันทึกไว้มาก่อนฉบับของ AI เสมอ**
  // (deps เป็นค่าจากเซิร์ฟเวอร์ ไม่ใช่ค่าในช่อง จึงไม่ทับสิ่งที่กำลังพิมพ์อยู่ตอน poll)
  useEffect(() => {
    const body = c?.email_draft_edited?.body ?? c?.email_draft?.body;
    if (body) setEmailBody(body);
  }, [c?.email_draft_edited?.body, c?.email_draft?.body]);
  useEffect(() => {
    const subject = c?.email_draft_edited?.subject ?? c?.email_draft?.subject;
    if (subject) setEmailSubject(subject);
  }, [c?.email_draft_edited?.subject, c?.email_draft?.subject]);
  // เตือนก่อนปิดแท็บ/ออกจากหน้าเมื่อร่างยังไม่ได้บันทึก — เบราว์เซอร์แสดงข้อความของตัวเอง
  // (กำหนดข้อความเองไม่ได้) แค่ preventDefault ก็พอให้ถามก่อน
  useEffect(() => {
    if (!unsavedRef.current) return;
    const warn = (e: BeforeUnloadEvent) => {
      if (!unsavedRef.current) return;
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  });

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
      // relative_to: backend ไม่คืนตัวเอง และติดป้ายแถวที่เป็นคนเดียวกัน
      // กรองซ้ำฝั่งนี้ไว้ด้วย เผื่อ backend รุ่นเก่าที่ยังไม่รู้จักพารามิเตอร์นี้
      const found = await searchCandidates(query.trim(), 10, candidate_id);
      setHits(found.filter((h) => h.id !== candidate_id));
    } catch (e) {
      setSearchError(e instanceof Error ? e.message : "ค้นหาไม่สำเร็จ");
      setHits(null);
    } finally {
      setSearching(false);
    }
  }

  /** บันทึกสิ่งที่พิมพ์อยู่ตอนนี้เป็นร่างของ HR — ไม่ส่งอะไรทั้งสิ้น */
  async function handleSaveDraft() {
    setSavingDraft(true);
    setDraftError(null);
    try {
      await saveEmailDraft(candidate_id, emailSubject, emailBody, mode);
      await mutate();
      setTextKind(null);
    } catch (e) {
      setDraftError(e instanceof Error ? e.message : "บันทึกร่างไม่สำเร็จ");
    } finally {
      setSavingDraft(false);
    }
  }

  /** ทิ้งร่างของ HR แล้วเอาร่างของ AI กลับมาใส่ช่อง (ร่างของ AI ไม่เคยถูกแตะ) */
  async function handleRevertDraft() {
    if (!confirm("ทิ้งร่างที่แก้ไว้ แล้วกลับไปใช้ร่างของ AI?")) return;
    setSavingDraft(true);
    setDraftError(null);
    try {
      await clearEmailDraft(candidate_id);
      if (c?.email_draft) {
        setEmailSubject(c.email_draft.subject);
        setEmailBody(c.email_draft.body);
      }
      setTextKind(null);
      await mutate();
    } catch (e) {
      setDraftError(e instanceof Error ? e.message : "ยกเลิกร่างไม่สำเร็จ");
    } finally {
      setSavingDraft(false);
    }
  }

  /** เติมร่างปฏิเสธตั้งต้นลงช่อง — ถามก่อนถ้ามีข้อความที่ยังไม่บันทึก จะได้ไม่ทับงานที่พิมพ์ไว้ */
  function handleUseRejection() {
    if (unsavedRef.current && !confirm("ข้อความที่แก้ไว้ยังไม่ได้บันทึก จะแทนที่ด้วยร่างปฏิเสธไหม?"))
      return;
    const vars = { candidate_name: c?.full_name ?? "", job_title: job?.title ?? "" };
    setEmailSubject(fillTemplate(DEFAULT_REJECTION.subject, vars));
    setEmailBody(fillTemplate(DEFAULT_REJECTION.body, vars));
    setTextKind("rejection");
  }

  async function handleSend(acknowledged = false) {
    setSending(true);
    setSendError(null);
    try {
      await sendEmail(candidate_id, {
        to: emailTo,
        subject: emailSubject,
        body: emailBody,
        acknowledged_bias_warning: acknowledged,
      });
      setBiasWarning(null);
      mutate(); // ดึง email_sent_at ล่าสุดมาแสดงป้าย "ส่งแล้ว"
    } catch (e) {
      // backend ตรวจถ้อยคำที่อาจเป็นการเลือกปฏิบัติก่อนส่งเสมอ — เจอแล้วยังไม่ยืนยัน = ยังไม่ส่ง
      // ถามให้ HR เลือก: กลับไปแก้ หรือส่งต่อ (บางงานจำเป็นจริง ระบบไม่ห้าม แต่ต้องรู้ตัวก่อน)
      const phrases = biasWarningOf(e);
      if (phrases) setBiasWarning(phrases);
      else setSendError(e instanceof Error ? e.message : "ส่งอีเมลไม่สำเร็จ");
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

  if (gone)
    return (
      <div className="space-y-md">
        <Breadcrumb
          items={[
            { label: "ตำแหน่งงาน", href: "/" },
            ...(job ? [{ label: job.title, href: `/jobs/${id}` }] : []),
            { label: "ไม่พบ" },
          ]}
        />
        {/* ผู้สมัครหาย แต่ตำแหน่งยังอยู่ → พากลับไปตำแหน่งนั้น · ตำแหน่งหายด้วย → หน้าตำแหน่งงาน */}
        <NotFoundCard
          title="ไม่พบผู้สมัครคนนี้"
          backHref={job ? `/jobs/${id}` : "/"}
          backLabel={job ? `กลับไปหน้า ${job.title}` : "กลับไปหน้าตำแหน่งงาน"}
        />
      </div>
    );

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
        <p className="text-outline text-label-md flex items-center gap-xs" role="status">
          <Spinner className="text-[18px]" />
          กำลังโหลด…
        </p>
      </div>
    );

  const band = BANDS[scoreBand(c.fit_score)];
  const profile = c.parsed_resume;
  // ร่างที่บันทึกไว้ล่าสุด (ของ HR ถ้ามี ไม่งั้นของ AI) — ใช้เทียบว่ามีอะไรยังไม่ได้บันทึก
  const savedSubject = c.email_draft_edited?.subject ?? c.email_draft?.subject ?? "";
  const savedBody = c.email_draft_edited?.body ?? c.email_draft?.body ?? "";
  // มีร่างให้แก้ถ้ามีฝั่งใดฝั่งหนึ่ง — runner ตั้ง email_draft เป็น NULL ได้เมื่อ drafter ล้ม
  // ถ้าผูกฟอร์มไว้กับร่างของ AI อย่างเดียว ร่างที่ HR บันทึกไว้จะเข้าไม่ถึงทั้งที่ยังอยู่ใน DB
  const hasDraft = Boolean(c.email_draft || c.email_draft_edited);
  // โหมดของการ์ด (เชิญ/ปฏิเสธ) — สัมภาษณ์ไม่ผ่านหรือไม่ไปต่อแล้วต้องเป็นปฏิเสธ ไม่งั้น
  // ตัวเลือกเทมเพลตซ่อนเทมเพลตปฏิเสธไว้ (กติกาทั้งหมดอยู่ใน lib/email-draft.ts::emailMode)
  const mode = emailMode({
    interviewResult: c.interview_outcome?.result,
    boardStage: c.board_stage,
    aiDraftKind: c.email_draft?.kind,
    hrDecision: c.hr_decision,
    offerResponse: c.offer?.response,
  });
  // ชนิดของร่างที่บันทึกไว้ — ร่างของ HR ที่บันทึกก่อนมีฟิลด์ kind ถือว่าเป็นชนิดเดียวกับร่างของ AI
  const savedKind =
    (c.email_draft_edited ? c.email_draft_edited.kind : undefined) ??
    c.email_draft?.kind ??
    mode;
  const fieldsKind = textKind ?? savedKind;
  const draftDirty =
    hasDraft && (emailSubject !== savedSubject || emailBody !== savedBody);
  unsavedRef.current = draftDirty;

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
                    {/* หน้านี้มีปุ่มตัดสิน → รูปขึ้นเฉพาะเมื่อ HR เปิดสวิตช์ในหน้าตั้งค่า */}
                    <CandidateAvatar
                      candidateId={candidate_id}
                      name={c.full_name}
                      show={showPhoto}
                      className="w-full h-full rounded-full flex items-center justify-center text-headline-md font-semibold bg-primary-container text-on-primary"
                    />
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

              {/* เทียบไฟล์จริงกับสิ่งที่ระบบอ่านได้ — ไฟล์มีเฉพาะคนที่เข้ามาหลังเริ่มเก็บ */}
              <ResumeSource
                candidateId={candidate_id}
                candidateName={c.full_name}
                hasFile={c.has_resume_file}
                text={c.raw_resume_text}
                photosHidden={!showPhoto}
              />

            </div>

            {/* ขวา: Gap Analysis */}
            <div className="flex-1 space-y-md">
              <div className="ai-glow-border p-md rounded-xl bg-glass/40">
                <h3 className="text-headline-md text-primary flex items-center gap-xs mb-xs">
                  <span className="material-symbols-outlined">query_stats</span>
                  Gap Analysis
                </h3>
                {c.gap_analysis && (
                  <p className="text-label-md text-on-surface-variant mb-xs">
                    ตรงตามทักษะที่ต้องมี{" "}
                    <b className="text-on-surface">
                      {c.gap_analysis.matched_required.length}/
                      {c.gap_analysis.matched_required.length +
                        c.gap_analysis.missing_required.length}
                    </b>{" "}
                    ข้อ และทักษะที่อยากได้{" "}
                    <b className="text-on-surface">
                      {c.gap_analysis.matched_preferred.length}/
                      {c.gap_analysis.matched_preferred.length +
                        c.gap_analysis.missing_preferred.length}
                    </b>{" "}
                    ข้อ
                  </p>
                )}
                <RadarChart gap={c.gap_analysis} />
              </div>
              {/* คู่กับเรดาร์: เรดาร์บอกว่าทักษะไหนตรง แท่งนี้บอกว่าแปลงเป็นคะแนนยังไง
                  ไม่มีผลวิเคราะห์ (gap_analysis เป็น null) = ไม่แสดง */}
              {c.gap_analysis && c.score_breakdown && c.fit_score != null && (
                <ScoreBreakdown breakdown={c.score_breakdown} fitScore={c.fit_score} />
              )}
            </div>
          </div>

          {/* ใต้สองคอลัมน์: ของที่อ่านง่ายกว่าเมื่อเต็มความกว้าง — เดิมกองอยู่ในคอลัมน์ขวา
              คอลัมน์ซ้ายจึงเหลือพื้นที่ว่างยาวลงไปจนสุดการ์ด */}
          <div className="mt-md space-y-md">
            {/* ผลตรวจอคติเป็นบรรทัดสั้น ๆ — วางคู่กันเฉพาะตอนมีทั้งสองใบ
                ใบเดียวแล้วบังคับครึ่งจอจะเหลือที่ว่างข้างเดียวอีก */}
            <div
              className={`grid gap-md ${c.bias_revision ? "lg:grid-cols-2" : ""}`}
            >
              {/* ผลตรวจอคติ — อ่านจากตำแหน่งสด ๆ (HR ยืนยันถ้อยคำทีหลังก็เห็นทันที)
                  ถอยไปใช้ audit_log ของผลประเมินเฉพาะตำแหน่งที่ยังไม่มีผลตรวจ */}
              {c.job_bias ? (
                <CandidateBiasBox bias={c.job_bias} />
              ) : c.audit_log && (
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
                    {/* ตัวเลขข้างบนเป็นของตอนที่ลูปทำงาน — ถ้า HR ยืนยันทักษะนั้นทีหลัง คะแนนถูกคิดใหม่แล้ว
                        ต้องบอก ไม่งั้นกล่องนี้ขัดกับคะแนนปัจจุบันที่เห็นด้านบน */}
                    {(() => {
                      const later = (c.job_bias?.acknowledged ?? [])
                        .filter((a) => a.kind === "skill")
                        .map((a) => a.phrase)
                        .filter((p) =>
                          [
                            ...c.bias_revision!.excluded_required,
                            ...c.bias_revision!.excluded_preferred,
                          ].includes(p),
                        );
                      return later.length > 0 ? (
                        <p className="text-label-sm text-on-surface-variant mt-1">
                          HR ยืนยันภายหลังว่า {later.join(", ")} จำเป็นกับงานนี้ — คะแนนปัจจุบันนับทักษะนี้แล้ว (
                          {c.fit_score ?? "—"})
                        </p>
                      ) : null;
                    })()}
                  </div>
                </div>
              )}
            </div>

            {/* คู่กับที่มาของคะแนน: อันนั้นบอกว่าได้มายังไง อันนี้บอกว่าอยู่ตรงไหนเทียบคนอื่น
                มีคนที่มีคะแนนน้อยกว่า 3 คน = ไม่มีใครให้เทียบ กราฟจะเหลือแท่งเดียวกับที่ว่าง
                ทั้งใบ จึงบอกเป็นประโยคแทน */}
            {c.fit_score != null && distribution && distribution.total >= 3 && (
              <ScoreHistogram data={distribution} highlightScore={c.fit_score} />
            )}
            {c.fit_score != null && distribution && distribution.total < 3 && (
              <p className="text-label-sm text-on-surface-variant">
                ยังเทียบคะแนนกับผู้สมัครคนอื่นไม่ได้ — ตำแหน่งนี้มีผู้ที่มีผลคะแนนแล้ว{" "}
                {distribution.total} คน
              </p>
            )}
            <SkillGap gap={c.gap_analysis} evidence={c.skill_evidence} />
          </div>
        </div>
      </div>

      {/* เส้นทางของผู้สมัคร — ประวัติ + ขั้นที่ยังไม่ถึง + ปุ่มย้ายขั้น รวมอยู่ในบล็อกเดียว
          (เดิมแยกเป็นไทม์ไลน์กับแถบ "ความคืบหน้าหลังผ่านคัดกรอง" ซึ่งซ้ำกันสามขั้น) */}
      <CandidateTimeline
        candidate={c}
        candidateId={candidate_id}
        jobId={id}
        onChanged={() => mutate()}
        onHire={() => setShowHire(true)}
      />

      {/* คำถามสัมภาษณ์ + ร่างอีเมล */}
      <div className="grid gap-md lg:grid-cols-2">
        <section className="glass-card rounded-2xl p-md">
          {/* ปุ่มวันนัดอยู่มุมขวาบนของการ์ด ระดับเดียวกับหัวข้อ — เป็นการกระทำของทั้งการ์ด
              ไม่ใช่ของบล็อกใดบล็อกหนึ่งข้างใน */}
          <div className="flex items-start justify-between gap-xs flex-wrap mb-sm">
            <h3 className="text-headline-md text-on-surface flex items-center gap-xs">
              <span className="material-symbols-outlined text-primary">quiz</span>
              คำถามสัมภาษณ์
            </h3>
            {c.board_stage && c.board_stage !== "hired" && c.board_stage !== "declined" && (
              <button
                className="btn-tonal text-label-sm py-1"
                onClick={() => setShowSchedule(true)}
              >
                <span className="material-symbols-outlined text-[16px]">event</span>
                {c.scheduled_at ? "แก้วันนัดสัมภาษณ์" : "เพิ่มวันนัดสัมภาษณ์"}
              </button>
            )}
          </div>
          {/* วันนัดอยู่เหนือคำถาม: HR เปิดหน้านี้ก่อนเข้าห้องสัมภาษณ์ สิ่งแรกที่ต้องรู้คือนัดกี่โมงที่ไหน
              กรอก/แก้ได้จากปุ่มมุมขวาบน ใช้โมดัลและ endpoint ตัวเดียวกับหน้ากระดาน (setStage
              บนแถว hiring_stage เดียวกัน คนละหนึ่งแถว) สองหน้าจึงไม่มีทางเห็นวันนัดไม่ตรงกัน */}
          {c.scheduled_at && (
            <div className="mb-sm">
              <InterviewScheduleSummary
                scheduledAt={c.scheduled_at}
                location={c.location}
                candidateName={c.full_name}
                jobTitle={job?.title}
              />
            </div>
          )}
          {normalizeQuestions(c.interview_plan).length === 0 && c.queue_status ? (
            <WorkingNote status={c.queue_status} what="คำถามสัมภาษณ์" />
          ) : (
            <InterviewGuide plan={c.interview_plan} />
          )}

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
            {hasDraft && (
              <span
                className={`text-label-sm px-2.5 py-1 rounded-full ${
                  mode === "invitation"
                    ? "bg-secondary-container/40 text-on-secondary-container"
                    : "bg-error-container/60 text-on-error-container"
                }`}
              >
                {mode === "invitation" ? "เชิญสัมภาษณ์" : "ปฏิเสธ"}
              </span>
            )}
          </h3>
          {hasDraft ? (
            <div className="space-y-xs">
              {c.email_sent_at && (
                <div className="flex items-center gap-xs text-label-md text-secondary rounded-lg bg-secondary-container/20 px-sm py-xs">
                  <span
                    className="material-symbols-outlined text-[18px]"
                    style={{ fontVariationSettings: "'FILL' 1" }}
                  >
                    mark_email_read
                  </span>
                  {/* ระบบรู้แค่ว่าส่งไปกี่ครั้ง ไม่รู้ว่าฉบับไหน — โหมดปฏิเสธจึงต้องบอกว่า
                      "รวมทุกฉบับ" ไม่งั้นอ่านเหมือนอีเมลปฏิเสธถูกส่งไปแล้ว */}
                  <span>
                    {c.email_send_count > 0 && (
                      <span className="font-semibold">
                        {mode === "rejection"
                          ? `เคยส่งอีเมลถึงผู้สมัครรายนี้แล้ว ${c.email_send_count} ครั้ง (รวมทุกฉบับ) · `
                          : `ส่งแล้ว ${c.email_send_count} ครั้ง · `}
                      </span>
                    )}
                    ล่าสุดถึง {c.email_sent_to} เมื่อ{" "}
                    {new Date(c.email_sent_at).toLocaleString("th-TH")}
                  </span>
                </div>
              )}

              {/* โหมดปฏิเสธแต่ข้อความในช่องยังเป็นร่างเชิญ — ร่างของ AI ถูกสร้างครั้งเดียว
                  ตอนผ่านคัดกรอง ระบบไม่ร่างใหม่หลังสัมภาษณ์ จึงให้เริ่มจากร่างตั้งต้นได้ในคลิกเดียว */}
              {mode === "rejection" && fieldsKind === "invitation" && (
                <div
                  role="note"
                  className="flex items-start gap-xs p-sm rounded-lg border border-tertiary/40 bg-tertiary-container/10"
                >
                  <span className="material-symbols-outlined text-tertiary text-[18px] flex-none">
                    swap_horiz
                  </span>
                  <p className="text-label-md text-on-surface flex-1 min-w-0">
                    ร่างที่มีอยู่เป็นแบบเชิญสัมภาษณ์ — ใช้ร่างปฏิเสธตั้งต้น หรือเลือกเทมเพลตปฏิเสธด้านล่าง
                  </p>
                  <button
                    type="button"
                    className="btn-tonal text-label-sm py-1 flex-none"
                    onClick={handleUseRejection}
                  >
                    ใช้ร่างปฏิเสธ
                  </button>
                </div>
              )}

              {/* กลับกัน: บันทึกร่างปฏิเสธไว้ แล้ว HR ดึงผู้สมัครกลับเข้ากระบวนการ — กันส่งพลาด */}
              {mode === "invitation" && fieldsKind === "rejection" && (
                <div
                  role="note"
                  className="flex items-start gap-xs p-sm rounded-lg border border-error/40 bg-error-container/10"
                >
                  <span className="material-symbols-outlined text-error text-[18px] flex-none">
                    warning
                  </span>
                  <p className="text-label-md text-on-surface flex-1 min-w-0">
                    ร่างที่บันทึกไว้เป็นแบบปฏิเสธ แต่ผู้สมัครกลับเข้ากระบวนการแล้ว — ตรวจก่อนส่ง
                  </p>
                  {c.email_draft_edited && c.email_draft && (
                    <button
                      type="button"
                      className="btn-tonal text-label-sm py-1 flex-none"
                      onClick={handleRevertDraft}
                      disabled={savingDraft}
                    >
                      กลับไปใช้ร่างของ AI
                    </button>
                  )}
                </div>
              )}

              {/* เทมเพลตที่บันทึกไว้ — เติมช่องให้เฉย ๆ HR ยังต้องตรวจและกดส่งเอง */}
              <EmailTemplatePicker
                kind={mode}
                subject={emailSubject}
                body={emailBody}
                vars={{
                  candidate_name: c.full_name,
                  job_title: job?.title ?? "",
                  // ยังไม่มีวันนัด = ไม่ส่งค่า → fillTemplate ปล่อย {interview_datetime}
                  // ค้างไว้ให้เห็น ไม่แทนด้วยค่าว่างจนอ่านไม่ออกว่าตกอะไรไป
                  interview_datetime: c.scheduled_at
                    ? formatSchedule(c.scheduled_at)
                    : null,
                  interview_location: c.location,
                }}
                onApply={(s, b) => {
                  // ตัวเลือกกรองตามโหมดอยู่แล้ว เทมเพลตที่เลือกจึงเป็นชนิดเดียวกับโหมด
                  setTextKind(mode);
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

              {/* แทรกวันนัดลงเนื้อความ — ระบบรู้วันนัดอยู่แล้ว ไม่ควรให้ HR พิมพ์เอง
                  กดซ้ำไม่ได้บรรทัดซ้ำ (appendScheduleLine เช็คให้) · เฉพาะโหมดเชิญ */}
              {mode === "invitation" && c.scheduled_at && (
                <button
                  type="button"
                  className="btn-secondary-glass text-label-sm py-1"
                  onClick={() =>
                    setEmailBody((prev) =>
                      appendScheduleLine(
                        prev,
                        scheduleLine(formatSchedule(c.scheduled_at!), c.location),
                      ),
                    )
                  }
                >
                  <span className="material-symbols-outlined text-[16px]">event</span>
                  แทรกวันนัดลงในอีเมล
                </button>
              )}

              {/* เชิญสัมภาษณ์แต่ยังไม่มีวันนัดในระบบ — ส่งไปแล้วตารางสัมภาษณ์จะว่างเปล่า
                  และผู้สมัครก็ไม่รู้ว่าต้องมาวันไหน */}
              {mode === "invitation" && !c.scheduled_at && (
                <div
                  role="note"
                  className="flex items-start gap-xs p-sm rounded-lg border border-tertiary/40 bg-tertiary-container/10"
                >
                  <span className="material-symbols-outlined text-tertiary text-[18px] flex-none">
                    event_busy
                  </span>
                  <p className="text-label-md text-on-surface flex-1 min-w-0">
                    ยังไม่มีวันนัดในระบบ — อีเมลเชิญที่ไม่มีวันเวลาจะทำให้ผู้สมัครต้องถามกลับ
                    และนัดนี้จะไม่ขึ้นในตารางสัมภาษณ์
                  </p>
                  {c.board_stage && c.board_stage !== "hired" && c.board_stage !== "declined" && (
                    <button
                      className="btn-tonal text-label-sm py-1 flex-none"
                      onClick={() => setShowSchedule(true)}
                    >
                      เพิ่มวันนัด
                    </button>
                  )}
                </div>
              )}

              {/* บันทึกร่าง — เดิมที่พิมพ์แก้อยู่ในหน้าจอเท่านั้น ออกจากหน้าแล้วหายหมด
                  ไม่ autosave: กดเองชัดเจนกว่า และไม่ยิง request รัว ๆ ระหว่างพิมพ์ */}
              <div className="flex items-center gap-xs flex-wrap pt-xs border-t border-outline-variant/40">
                <button
                  type="button"
                  onClick={handleSaveDraft}
                  disabled={savingDraft || !draftDirty || !emailSubject || !emailBody}
                  className="btn-tonal text-label-sm py-1 disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-[16px]">save</span>
                  {savingDraft && <Spinner className="text-[16px]" />}
                  {savingDraft ? "กำลังบันทึก…" : "บันทึกร่าง"}
                </button>
                {draftDirty ? (
                  <span className="text-label-sm text-tertiary">ยังไม่ได้บันทึก</span>
                ) : c.email_draft_edited_at ? (
                  <span className="text-label-sm text-on-surface-variant">
                    ร่างที่คุณแก้ไว้ · บันทึกเมื่อ{" "}
                    {new Date(c.email_draft_edited_at).toLocaleString("th-TH", {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })}
                  </span>
                ) : (
                  <span className="text-label-sm text-outline">ร่างของ AI</span>
                )}
                {c.email_draft_edited && (
                  <button
                    type="button"
                    onClick={handleRevertDraft}
                    disabled={savingDraft}
                    className="text-label-sm text-on-surface-variant hover:text-primary ms-auto"
                  >
                    กลับไปใช้ร่างของ AI
                  </button>
                )}
              </div>

              {draftError && (
                <p className="text-error text-label-md" role="alert">
                  {draftError}
                </p>
              )}

              {sendError && (
                <p className="text-error text-label-md" role="alert">
                  {sendError}
                </p>
              )}

              <button
                onClick={() => {
                  if (
                    c.email_sent_at &&
                    !confirm(
                      mode === "rejection"
                        ? `เคยส่งอีเมลถึงผู้สมัครรายนี้แล้ว ${c.email_send_count} ครั้ง (เช่นอีเมลเชิญ) ยืนยันส่งอีเมลปฏิเสธ?`
                        : "อีเมลนี้เคยส่งไปแล้ว ยืนยันส่งซ้ำ?",
                    )
                  )
                    return;
                  handleSend();
                }}
                disabled={sending || !emailTo || !emailSubject || !emailBody}
                className="btn-primary w-full disabled:opacity-50"
              >
                {sending ? (
                  <Spinner className="text-[18px]" />
                ) : (
                  <span className="material-symbols-outlined text-[18px]">send</span>
                )}
                {sending
                  ? "กำลังส่ง…"
                  : mode === "rejection"
                    ? "ส่งอีเมลปฏิเสธ"
                    : c.email_send_count > 0
                      ? `ส่งซ้ำ (ส่งแล้ว ${c.email_send_count} ครั้ง)`
                      : "ส่งอีเมล"}
              </button>

              {biasWarning && (
                <ConfirmDialog
                  title="อีเมลนี้มีถ้อยคำที่อาจเป็นการเลือกปฏิบัติ"
                  body={
                    <div className="space-y-xs">
                      <ul className="flex flex-wrap gap-base">
                        {biasWarning.map((w) => (
                          <li
                            key={w.phrase}
                            className="text-label-sm px-2 py-0.5 rounded-full bg-tertiary/15 text-on-surface"
                          >
                            “{w.phrase}” <span className="text-outline">({w.category})</span>
                          </li>
                        ))}
                      </ul>
                      <p>
                        ยังไม่ได้ส่ง · ถ้อยคำพวกนี้ถึงมือผู้สมัครจริง กด “ยกเลิก” เพื่อกลับไปแก้
                        ถ้างานนี้จำเป็นจริงกด “ส่งต่อ” — ระบบจะบันทึกว่าคุณส่งทั้งที่ถูกเตือน
                      </p>
                    </div>
                  }
                  confirmLabel="ส่งต่อ"
                  busy={sending}
                  error={sendError}
                  onConfirm={() => handleSend(true)}
                  onClose={() => setBiasWarning(null)}
                />
              )}
            </div>
          ) : (
            c.queue_status ? (
              <WorkingNote status={c.queue_status} what="ร่างอีเมล" />
            ) : (
              <p className="text-label-md text-outline">ยังไม่มีร่างอีเมล</p>
            )
          )}
        </section>
      </div>

      {/* ผู้สมัครคล้ายกัน — การ์ดเดียว สองแหล่ง:
          (1) similar_candidates มาจาก retrieve_similar node ตอนรันกราฟ บันทึกผูกกับผู้สมัครคนนี้
          (2) ค้นเพิ่มเอง ยิง GET /candidates/search สดทุกครั้ง ไม่ persist
          เดิมแยกสองการ์ด ทั้งที่ตอบคำถามเดียวกัน ("มีใครคล้ายคนนี้") */}
      <section className="glass-card rounded-2xl p-md">
        <h3 className="text-headline-md text-on-surface flex items-center gap-xs">
          <span className="material-symbols-outlined text-primary">group</span>
          ผู้สมัครที่โปรไฟล์คล้ายกัน
        </h3>
        <p className="text-label-sm text-outline mb-sm">
          จากคลังผู้สมัครเก่า — ใช้เป็นบริบทเทียบเคียง ไม่มีผลต่อคะแนนของผู้สมัครรายนี้
        </p>

        {c.similar_candidates && c.similar_candidates.length > 0 ? (
          <>
            <p className="text-label-sm text-on-surface-variant mb-xs">
              ระบบแนะนำตอนวิเคราะห์
            </p>
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
                  <SimilarityMeta
                    fitScore={s.fit_score}
                    distance={s.distance}
                    samePerson={s.same_person}
                  />
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-label-md text-outline">
            ตอนวิเคราะห์ระบบไม่พบผู้สมัครที่คล้ายกัน — ลองค้นเองด้านล่าง
          </p>
        )}

        <div className="border-t border-outline-variant/40 mt-md pt-md">
        <p className="text-label-sm text-on-surface-variant mb-xs">
          ค้นเพิ่มเติม{" "}
          <span className="text-outline">
            — คำค้นเริ่มต้นมาจากตำแหน่งงานและทักษะของผู้สมัครรายนี้ แก้ได้ (ผลไม่ถูกบันทึก)
          </span>
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
            {searching && <Spinner className="text-[16px]" />}
            {searching ? "กำลังค้นหา…" : "ค้นหา"}
          </button>
          {/* ล้างผลค้นหา — รายการยาวทำให้ต้องเลื่อนผ่านทุกครั้งที่กลับมาหน้านี้
              ล้างแค่ผล ไม่ล้างคำค้น จะได้กดค้นซ้ำได้ทันที (ผลไม่เคยถูกบันทึกอยู่แล้ว) */}
          {(hits !== null || searchError) && (
            <button
              onClick={() => {
                setHits(null);
                setSearchError(null);
              }}
              disabled={searching}
              className="btn-secondary-glass md:w-auto justify-center"
            >
              <span className="material-symbols-outlined text-[18px]">close</span>
              ล้างผล
            </button>
          )}
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
            <>
            <p className="text-label-sm text-on-surface-variant mt-sm">
              ผลค้นหา {hits.length} คน
            </p>
            <ul className="space-y-xs mt-xs">
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
                    <SimilarityMeta
                      fitScore={h.fit_score}
                      distance={h.distance}
                      samePerson={h.same_person}
                    />
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
            </>
          ))}
        </div>
      </section>

      {/* Human-in-the-Loop */}
      <div className="glass-card rounded-2xl p-md space-y-sm">
        <h3 className="text-headline-md text-on-surface">ผลคัดกรองโดย HR</h3>

        {/* HR แก้เกณฑ์ทักษะของตำแหน่งจนคะแนนคนนี้ข้ามแบนด์ — ระบบไม่เดินกราฟใหม่เอง
            คำถาม/ร่างอีเมลที่มีอยู่ยังเป็นของเกณฑ์เดิม ถ้าตัดสินใหม่ กราฟจะใช้เกณฑ์ล่าสุด
            วางนอกเงื่อนไขซ่อนข้อความด้านล่างด้วยเหตุผลเดียวกับแถบหยุดกลางทาง */}
        {c.needs_recheck && (
          <div
            role="note"
            className="rounded-xl border border-tertiary/40 bg-tertiary-container/10 p-sm flex items-start gap-xs"
          >
            <span
              className="material-symbols-outlined text-tertiary text-[20px] flex-none"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              rule
            </span>
            <p className="text-label-md text-on-surface">
              เกณฑ์ทักษะของตำแหน่งนี้ถูกแก้ คะแนนเปลี่ยนจาก {c.rescored_from} เป็น{" "}
              {c.fit_score} จนข้ามแบนด์ — คำถามสัมภาษณ์และร่างอีเมลด้านบนยังเป็นของเกณฑ์เดิม
              ตรวจแล้วตัดสินใหม่ได้ด้วยปุ่มด้านล่าง ระบบจะใช้เกณฑ์ล่าสุด
            </p>
          </div>
        )}

        {/* กราฟหยุดกลางทาง — วางไว้นอกเงื่อนไขด้านล่างโดยตั้งใจ: คนที่เจอเคสนี้มักตัดสิน
            ไปแล้ว (อนุมัติแล้วแต่ร่างอีเมลล้ม) ซึ่งข้อความด้านล่างถูกซ่อนเมื่อมีคำตัดสิน
            ถ้าวางข้างในแถบนี้จะไม่โผล่ให้คนที่ต้องการมันที่สุดเห็นเลย */}
        {c.graph_status === "interrupted" && (
          <div className="rounded-xl border border-tertiary/40 bg-tertiary-container/10 p-sm flex flex-wrap items-center gap-xs">
            <span
              className="material-symbols-outlined text-tertiary text-[20px] flex-none"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              warning
            </span>
            <p className="text-label-md text-on-surface min-w-0 flex-1">
              การประมวลผลหยุดกลางทาง — ผลที่ทำเสร็จแล้วเก็บไว้ครบ
              กดเพื่อทำขั้นที่เหลือต่อ ระบบจะไม่เริ่มวิเคราะห์ใหม่ตั้งแต่ต้น
            </p>
            <button
              className="btn-tonal"
              disabled={resuming}
              onClick={async () => {
                setResuming(true);
                setResumeError(null);
                try {
                  await resumeCandidate(candidate_id);
                  mutate();
                } catch (e) {
                  setResumeError(e instanceof Error ? e.message : "สั่งทำต่อไม่สำเร็จ");
                } finally {
                  setResuming(false);
                }
              }}
            >
              <span className="material-symbols-outlined text-[18px]">play_arrow</span>
              {resuming && <Spinner className="text-[16px]" />}
              {resuming ? "กำลังสั่ง…" : "ทำต่อจากจุดที่ค้าง"}
            </button>
            {resumeError && (
              <p className="text-error text-label-md w-full" role="alert">
                {resumeError}
              </p>
            )}
          </div>
        )}

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
            // ผ่านคัดกรองแล้ว แต่ต่อมาปิดกระบวนการ ("ไม่ไปต่อ" บนกระดาน) — คำตัดสินคัดกรอง
            // ยังเป็นความจริงอยู่ จึงไม่เปลี่ยนเป็น "ไม่ผ่าน" (และไม่แตะ hr_decision เด็ดขาด:
            // การเปลี่ยนคำตัดสินจะเข้าคิวให้กราฟตัดสินใหม่และเผาโควตา AI) · แต่กล่องสีเขียว
            // เฉย ๆ อ่านเหมือนผู้สมัครยังไปต่ออยู่ จึงลดเป็นสีกลางแล้วบอกสถานะตอนนี้ต่อท้าย
            const closedLater = approved && c.board_stage === "declined";
            return (
              <div
                className={`rounded-xl px-md py-sm border-2 ${
                  closedLater
                    ? "bg-glass/40 border-outline/40"
                    : approved
                      ? "bg-secondary-container/20 border-secondary/40"
                      : "bg-error-container/20 border-error/40"
                }`}
              >
                <div className="flex items-center justify-between gap-sm flex-wrap">
                  <div
                    className={`flex items-center gap-xs text-body-lg font-semibold ${
                      closedLater
                        ? "text-on-surface-variant"
                        : approved
                          ? "text-secondary"
                          : "text-error"
                    }`}
                  >
                    <span
                      className="material-symbols-outlined text-[26px]"
                      style={{ fontVariationSettings: "'FILL' 1" }}
                    >
                      {approved ? "check_circle" : "cancel"}
                    </span>
                    {/* เดิม "อนุมัติให้สัมภาษณ์แล้ว" — อ่านเหมือนนัดไปแล้ว ทั้งที่แค่ผ่านคัดกรอง
                        ความคืบหน้าจริงอยู่ในการ์ด "เส้นทางของผู้สมัคร" */}
                    {approved ? "ผ่านคัดกรองแล้ว" : "ไม่ผ่านคัดกรอง"}
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

                {/* สัมภาษณ์ไม่ผ่านเป็นสีแดงเฉพาะบรรทัดนี้ ไม่ใช่ทั้งกล่อง — กล่องแดงคู่กับหัวข้อ
                    "ผ่านคัดกรองแล้ว" จะอ่านเหมือนคำตัดสินคัดกรองผิด */}
                {closedLater &&
                  (c.offer?.response === "declined" ? (
                    // ผู้สมัครเป็นฝ่ายปฏิเสธ ไม่ใช่เราไม่รับ — สีกลาง ไม่ใช่สีแดง
                    <p className="mt-xs text-label-md text-on-surface flex items-center gap-xs">
                      <span className="material-symbols-outlined text-[18px] text-outline">
                        block
                      </span>
                      ตอนนี้: ผู้สมัครปฏิเสธข้อเสนอ และปิดกระบวนการแล้ว (ไม่ไปต่อ)
                      {c.offer.decline_reason && ` — ${c.offer.decline_reason}`}
                    </p>
                  ) : c.interview_outcome?.result === "fail" ? (
                    <p className="mt-xs text-label-md font-semibold text-error flex items-center gap-xs">
                      <span
                        className="material-symbols-outlined text-[18px]"
                        style={{ fontVariationSettings: "'FILL' 1" }}
                      >
                        cancel
                      </span>
                      ตอนนี้: สัมภาษณ์ไม่ผ่าน และปิดกระบวนการแล้ว (ไม่ไปต่อ)
                    </p>
                  ) : (
                    <p className="mt-xs text-label-md text-on-surface flex items-center gap-xs">
                      <span className="material-symbols-outlined text-[18px] text-outline">
                        block
                      </span>
                      ตอนนี้: ปิดกระบวนการแล้ว (ไม่ไปต่อ)
                    </p>
                  ))}

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
                  {busy === "approved" && <Spinner className="text-[16px]" />}
                  {busy === "approved" ? "กำลังส่ง…" : "ผ่านคัดกรอง"}
                </button>
                <button
                  onClick={() => decide("rejected")}
                  disabled={busy !== null}
                  className="flex-1 py-sm px-md bg-glass/80 text-error border-2 border-error/50 rounded-xl text-body-lg font-semibold flex items-center justify-center gap-xs hover:bg-error/5 active:scale-95 duration-200 disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-[26px]">cancel</span>
                  {busy === "rejected" && <Spinner className="text-[16px]" />}
                  {busy === "rejected" ? "กำลังส่ง…" : "ไม่ผ่านคัดกรอง"}
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

      {/* รับเข้าเป็นพนักงาน — โผล่ตั้งแต่ขั้น "สัมภาษณ์แล้ว" เป็นต้นไปเท่านั้น
          การจ้างสร้างระเบียนถาวร (1 คนได้ครั้งเดียว) ปุ่มแบบนี้ไม่ควรตั้งขวางหน้าคนที่ยังไม่มี
          ใครตัดสินด้วยซ้ำ — เดิมโผล่กับทุกคนที่ร่างอีเมลไม่ใช่แบบปฏิเสธ ซึ่งรวมคนที่เพิ่ง
          อัปโหลดเมื่อครู่และยังวิเคราะห์ไม่เสร็จ · เคสรีบยังกดได้ที่ขั้น "รับเข้าแล้ว" บนไทม์ไลน์
          ซึ่งเปิดหน้าต่างเดียวกัน จึงไม่ได้ปิดทาง แค่ไม่เอามาตั้งขวาง
          ถ้าจ้างแล้วสลับเป็นลิงก์ไปทะเบียนพนักงาน */}
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
        // การ์ดเปลี่ยนตามผลสัมภาษณ์ — ไม่ผ่านแล้วต้องไม่ถาม "สัมภาษณ์ผ่านแล้ว?" (ดูคอมโพเนนต์)
        (c.board_stage === "interviewed" || c.board_stage === "offer") && (
          <HireOrCloseCard
            candidateId={candidate_id}
            candidateName={c.full_name}
            jobTitle={job?.title ?? ""}
            boardStage={c.board_stage}
            result={c.interview_outcome?.result ?? null}
            offer={c.offer}
            onHire={() => setShowHire(true)}
            onChanged={() => mutate()}
          />
        )
      )}

      {showSchedule && c.board_stage && (
        <InterviewScheduleDialog
          candidateName={c.full_name}
          initialScheduledAt={c.scheduled_at}
          initialLocation={c.location}
          onSave={async (scheduledAt, location) => {
            // ส่งขั้นเดิมกลับไป = ไม่ย้ายขั้น (backend ไม่ขยับ moved_at) เหมือนที่กระดานทำ
            // ตั้งใจไม่ย้าย invited -> scheduled ให้อัตโนมัติ เพราะกระดานก็ไม่ย้าย
            // ถ้าที่นี่ย้ายเอง สองหน้าจะทำคนละอย่างกับการกระทำเดียวกัน
            await setStage(candidate_id, c.board_stage!, undefined, {
              scheduled_at: scheduledAt,
              location,
            });
            await mutate();
            setShowSchedule(false);
          }}
          onClose={() => setShowSchedule(false)}
        />
      )}

      {showHire && (
        <HireEmployeeDialog
          candidateId={candidate_id}
          defaultPosition={job?.title ?? ""}
          // มีข้อเสนอ → เติมตำแหน่ง เงินเดือน วันเริ่มงานจากข้อเสนอ HR ไม่ต้องพิมพ์ซ้ำ
          offer={c.offer}
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

/** ป้ายตัวเลขของแถวผู้สมัครคล้ายกัน — ติดคำกำกับทั้งสองค่า
 *  (เดิมแสดง "70%" ลอย ๆ ไม่รู้ว่าเป็นคะแนนหรือความคล้าย)
 *  ใช้สูตรเดียวกันทั้งรายการที่บันทึกไว้และผลค้นสด ตัวเลขจะได้อ่านเทียบกันได้
 *  แถวที่เป็นคนเดียวกันโชว์ป้ายแทน % — % เทียบรายการทักษะกับเรซูเม่ทั้งฉบับ ไฟล์เดียวกัน
 *  ยังได้แค่ ~78% ถ้าโชว์คู่กับคำว่า "คนเดียวกัน" จะดูขัดกันเอง */
const SAME_PERSON_LABEL: Record<SamePerson, { text: string; hint: string }> = {
  same_file: { text: "คนเดียวกัน · เคยสมัคร", hint: "เรซูเม่ไฟล์เดียวกัน" },
  same_email: {
    text: "น่าจะคนเดียวกัน · อีเมลตรงกัน",
    hint: "คนละไฟล์ แต่อีเมลในเรซูเม่ตรงกัน",
  },
};

function SimilarityMeta({
  fitScore,
  distance,
  samePerson,
}: {
  fitScore: number | null;
  distance: number | null;
  samePerson?: SamePerson | null;
}) {
  const same = samePerson ? SAME_PERSON_LABEL[samePerson] : null;
  return (
    <div className="flex items-center gap-sm flex-none text-right">
      {same ? (
        <span
          title={same.hint}
          className="text-[11px] font-semibold px-2.5 py-1 rounded-full bg-primary-fixed text-on-primary-fixed-variant"
        >
          {same.text}
        </span>
      ) : distance != null && (
        <span className="text-label-md text-on-surface">
          คล้าย {Math.round((1 - distance) * 100)}%
        </span>
      )}
      {fitScore != null && (
        <span className="text-label-sm text-outline">คะแนนเดิม {fitScore}</span>
      )}
    </div>
  );
}
