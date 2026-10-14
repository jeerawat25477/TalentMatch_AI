"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import AiInsight from "@/components/ai-insight";
import Breadcrumb from "@/components/breadcrumb";
import { BiasAckEditor, toAckIn, type AckMap } from "@/components/bias-ack";
import JDReviewCard from "@/components/jd-review-card";
import SkillListsEditor from "@/components/skill-lists-editor";
import type { SkillLists } from "@/components/skill-lists-editor";
import { analyzeJD, biasedSkillErrorOf, createJob, reviewJD } from "@/lib/api";
import type { JDReview, JobAnalyzeResult } from "@/lib/types";
import Spinner from "@/components/spinner";

// ตัวอย่างประกาศจริง ไม่ใช่คำสั่งว่าให้ทำอะไร — HR จะได้เห็นว่า "วางอะไรลงไป" ได้ทันที
// เขียนแบบที่ประกาศจริงเขียนกัน (มีหัวข้อ มีคำว่า "หรือ" มีส่วนที่มีก็ดี) ไม่ใช่รูปแบบในอุดมคติ
const PLACEHOLDER = `วางประกาศของคุณทับข้อความนี้ได้เลย เช่น

Senior Python Developer
หน้าที่: ดูแลระบบหลังบ้านและ API ร่วมกับทีม
คุณสมบัติ: ประสบการณ์ Python อย่างน้อย 3 ปี, FastAPI หรือ Django, PostgreSQL
จะพิจารณาเป็นพิเศษ: Docker, LangGraph
การศึกษา: ปริญญาตรีสาขาคอมพิวเตอร์`;

/**
 * สร้างตำแหน่งงาน — สองจังหวะ: วางประกาศ แล้ว **ยืนยันเกณฑ์** ก่อนบันทึก
 *
 * ที่มา: เดิมกดปุ่มเดียวแล้ว AI อ่านและบันทึกเกณฑ์ทันที HR เห็นเกณฑ์ก็ต่อเมื่อเข้าไปดูหน้าตำแหน่ง
 * ทีหลัง — ตำแหน่ง Junior Web Developer (2026-09-22) จึงมีผู้สมัครได้ 100 คะแนนจากเกณฑ์ที่ผิด
 * ก่อนที่ใครจะทันสังเกต · ตอนนี้ AI ร่างให้ คนตรวจและยืนยัน แล้วจึงบันทึก (มนุษย์อนุมัติ
 * แบบเดียวกับตอนคัดผู้สมัคร แต่ขยับมาตั้งแต่ตอนสร้างตำแหน่ง)
 *
 * AI ล้มหรือโควตาหมด → ยังสร้างตำแหน่งได้ โดย HR กรอกเกณฑ์เอง (ปุ่ม "กรอกเกณฑ์เอง")
 */
export default function NewJobPage() {
  const router = useRouter();
  const [rawText, setRawText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 409 biased_skill — แสดงติดปุ่มบันทึก ไม่ใช่กล่อง error ด้านบนที่พับอยู่ตอนยืนยันเกณฑ์
  const [skillWarning, setSkillWarning] = useState<string | null>(null);

  // ร่างจาก AI (null = HR กรอกเอง เพราะ AI อ่านไม่สำเร็จ) · ยังไม่ถูกบันทึกจนกว่าจะกดยืนยัน
  const [draft, setDraft] = useState<JobAnalyzeResult | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [lists, setLists] = useState<SkillLists>({ required: [], preferred: [] });
  const [title, setTitle] = useState("");
  const [years, setYears] = useState(0);
  const [education, setEducation] = useState("");
  // ถ้อยคำในผลตรวจอคติที่ HR ยืนยันว่าจำเป็น — ส่งไปพร้อมตอนสร้าง
  const [acks, setAcks] = useState<AckMap>({});

  // state ของการ "ตรวจ JD" แยกจากการวิเคราะห์เด็ดขาด — คนละปุ่ม คนละผลลัพธ์
  const [reviewing, setReviewing] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [review, setReview] = useState<JDReview | null>(null);

  function editText(next: string) {
    setRawText(next);
    if (review || reviewError) {
      setReview(null);
      setReviewError(null);
    }
  }

  async function handleReview() {
    if (!rawText.trim()) return;
    setReviewing(true);
    setReviewError(null);
    try {
      setReview(await reviewJD(rawText));
    } catch (e) {
      setReviewError(e instanceof Error ? e.message : "ตรวจประกาศไม่สำเร็จ");
    } finally {
      setReviewing(false);
    }
  }

  // ทักษะที่ AI ชี้ซึ่งยังอยู่ในรายการที่ HR กำลังแก้ — ลบออกแล้วปุ่มยืนยันก็หายไป
  // เทียบแบบหยาบ (ตัวพิมพ์ ช่องว่าง กลุ่ม "|") ถ้าพลาด ยืนยันที่การ์ดในหน้าตำแหน่งได้หลังสร้าง
  // (ใช้ผลจาก server) และ backend ทิ้งการยืนยันของทักษะที่ไม่อยู่ในเกณฑ์แล้วเอง
  const skillKey = (s: string) => s.trim().toLowerCase().replace(/\s+/g, " ");
  const listed = new Set(
    [...lists.required, ...lists.preferred].flatMap((s) => s.split("|")).map(skillKey),
  );
  const ackableSkills = (draft?.skill_phrases ?? []).filter((s) => listed.has(skillKey(s)));

  function startConfirm(d: JobAnalyzeResult | null) {
    setDraft(d);
    setLists({
      required: d?.required_skills ?? [],
      preferred: d?.preferred_skills ?? [],
    });
    setTitle(d?.job_title || rawText.trim().split("\n")[0].slice(0, 255));
    setYears(d?.min_experience_years ?? 0);
    setEducation(d?.education ?? "");
    setAcks({});
    setConfirming(true);
  }

  async function handleAnalyze() {
    if (!rawText.trim()) return;
    setBusy(true);
    setError(null);
    try {
      startConfirm(await analyzeJD(rawText));
    } catch (e) {
      setError(e instanceof Error ? e.message : "วิเคราะห์ไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  function backToText() {
    setConfirming(false);
    setError(null);
  }

  async function handleCreate() {
    setBusy(true);
    setError(null);
    setSkillWarning(null);
    try {
      const job = await createJob(rawText, {
        job_title: title.trim() || "Untitled Position",
        min_experience_years: years,
        education: education.trim(),
        required_skills: lists.required,
        preferred_skills: lists.preferred,
        extraction: draft?.extraction ?? null,
        // ผลตรวจอคติดิบของ AI — backend รวมกับกฎตายตัวใหม่เอง เก็บเป็นผลตรวจของตำแหน่ง
        bias_llm: draft?.bias_llm ?? null,
        bias_acks: toAckIn(acks),
      });
      router.push(`/jobs/${job.id}`);
    } catch (e) {
      const biased = biasedSkillErrorOf(e);
      if (biased) setSkillWarning(biased.message);
      else setError(e instanceof Error ? e.message : "สร้างตำแหน่งไม่สำเร็จ");
      setBusy(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-md">
      <Breadcrumb
        items={[{ label: "ตำแหน่งงาน", href: "/" }, { label: "สร้างตำแหน่งใหม่" }]}
      />

      <div>
        <h1 className="text-headline-lg text-on-surface">สร้างตำแหน่งงานใหม่</h1>
        <p className="text-body-md text-on-surface-variant">
          วางประกาศ แล้วตรวจเกณฑ์ที่ AI ร่างให้ ก่อนบันทึก
        </p>
      </div>

      {!confirming && (
        <AiInsight title="ทำงาน 2 ขั้น">
          <b className="text-on-surface">1.</b> วางประกาศแล้วกด “วิเคราะห์” — AI แยกให้เป็นทักษะที่ต้องมี
          ทักษะที่อยากได้ และประสบการณ์ขั้นต่ำ · <b className="text-on-surface">2.</b> คุณตรวจและแก้
          แล้วกดยืนยัน ตำแหน่งจึงถูกสร้าง · เกณฑ์ที่ยืนยันคือสิ่งที่ใช้ให้คะแนนผู้สมัครทุกคน
          แก้ทีหลังได้ตลอด
        </AiInsight>
      )}

      <div className="glass-card-elevated rounded-2xl p-md space-y-sm">
        {confirming ? (
          // ระหว่างยืนยันเกณฑ์: โชว์ประกาศแบบอ่านอย่างเดียว ให้ยังเทียบกับเกณฑ์ได้
          <details className="rounded-xl border border-outline-variant/40 p-sm">
            <summary className="text-label-md font-semibold text-on-surface cursor-pointer">
              ประกาศที่วางไว้ (กดเพื่อดู)
            </summary>
            <pre className="mt-xs whitespace-pre-wrap break-words font-sans text-label-md text-on-surface-variant max-h-60 overflow-y-auto">
              {rawText}
            </pre>
          </details>
        ) : (
          <textarea
            value={rawText}
            onChange={(e) => editText(e.target.value)}
            placeholder={PLACEHOLDER}
            rows={12}
            className="input-glass w-full resize-y"
          />
        )}

        {error && (
          <p className="text-error text-label-md" role="alert">
            {error}
          </p>
        )}
        {reviewError && !confirming && (
          <p className="text-error text-label-md" role="alert">
            {reviewError}
          </p>
        )}
        {/* AI อ่านไม่ได้ (โควตาหมด/ล่ม) ไม่ควรทำให้สร้างตำแหน่งไม่ได้เลย */}
        {error && !confirming && rawText.trim() && (
          <button
            onClick={() => startConfirm(null)}
            className="text-label-md text-primary hover:underline"
          >
            กรอกเกณฑ์เองแล้วสร้างตำแหน่ง
          </button>
        )}

        {!confirming && (
          <div className="flex justify-end gap-xs flex-wrap">
            <button onClick={() => router.push("/")} className="btn-secondary-glass">
              ยกเลิก
            </button>
            {/* ปุ่มตรวจแยกจากปุ่มวิเคราะห์โดยตั้งใจ — แต่ละครั้งกินโควตา AI */}
            <button
              onClick={handleReview}
              disabled={reviewing || busy || !rawText.trim()}
              className="btn-secondary-glass disabled:opacity-50"
            >
              {reviewing ? (
                <Spinner className="text-[18px]" />
              ) : (
                <span className="material-symbols-outlined text-[18px]">rate_review</span>
              )}
              {reviewing ? "กำลังตรวจประกาศ…" : "ตรวจประกาศก่อนวิเคราะห์"}
            </button>
            <button
              onClick={handleAnalyze}
              disabled={busy || !rawText.trim()}
              className="btn-primary"
            >
              {busy ? (
                <>
                  <Spinner className="text-[18px]" />
                  AI กำลังอ่านประกาศ…
                </>
              ) : (
                <>
                  <span className="material-symbols-outlined text-[18px]">auto_awesome</span>
                  วิเคราะห์
                </>
              )}
            </button>
          </div>
        )}
      </div>

      {review && !confirming && <JDReviewCard review={review} />}

      {confirming && (
        <div className="glass-card-elevated rounded-2xl p-md space-y-sm">
          <div>
            <h2 className="text-headline-md text-on-surface">ตรวจเกณฑ์ก่อนบันทึก</h2>
            <p className="text-label-md text-on-surface">
              {draft
                ? "AI ร่างจากประกาศให้แล้ว ยังไม่ได้บันทึก — แก้ได้ทุกช่อง กดที่ชื่อทักษะเพื่อดูว่ามาจากบรรทัดไหน"
                : "AI อ่านประกาศไม่สำเร็จ — กรอกเกณฑ์เองได้ที่นี่ แก้ทีหลังในหน้าตำแหน่งงานก็ได้"}
            </p>
            <p className="text-label-sm text-on-surface-variant mt-0.5">
              ทุกข้อในฝั่ง “ต้องมี” นับเป็นข้อบังคับ · ถ้ามีตัวใดตัวหนึ่งก็พอ ให้พิมพ์คั่นด้วย “หรือ”
              เช่น PyTorch หรือ TensorFlow (นับเป็น 1 ข้อ)
            </p>
          </div>

          {/* ตรวจอคติของประกาศครั้งเดียวตอนนี้ — ผู้สมัครทุกคนในตำแหน่งจะได้ผลเดียวกัน
              ไม่บล็อกการบันทึก HR ตัดสินเอง แต่ควรเห็นก่อนโพสต์ ไม่ใช่หลังมีคนสมัครแล้ว */}
          {draft?.bias.status === "flagged" && (
            <div
              role="alert"
              className="p-sm rounded-xl border border-tertiary/50 bg-tertiary-container/15 space-y-xs"
            >
              <p className="flex items-center gap-xs text-label-md font-semibold text-on-surface">
                <span
                  className="material-symbols-outlined text-tertiary text-[20px]"
                  style={{ fontVariationSettings: "'FILL' 1" }}
                  aria-hidden
                >
                  gpp_maybe
                </span>
                ประกาศนี้มีถ้อยคำที่อาจกีดกันผู้สมัคร
              </p>
              {draft.bias.jd_criteria.length > 0 ? (
                // งานบางแบบต้องการจริง (เช่นเพศหญิงสำหรับงานตรวจค้นตัว) — ยืนยันพร้อมเหตุผลได้
                // ถ้อยคำที่ยืนยันแล้วจะไม่ขึ้น ⚠ ในหน้าผู้สมัคร แต่บันทึกว่าใครยืนยันเพราะอะไร
                <BiasAckEditor
                  phrases={draft.bias.jd_criteria}
                  value={acks}
                  onChange={setAcks}
                  disabled={busy}
                />
              ) : (
                <p className="text-label-sm text-on-surface">{draft.bias.log.split("\n")[0]}</p>
              )}
              {ackableSkills.length > 0 && (
                <div className="space-y-xs">
                  <p className="text-label-sm text-on-surface">
                    <span className="font-semibold">ทักษะที่ AI ชี้ว่าอาจมีอคติ</span> — ไม่นับคะแนนจนกว่าจะยืนยัน
                    ลบออกจากรายการด้านล่างได้เลย หรือถ้างานต้องการจริง กด “จำเป็นกับงานนี้”
                  </p>
                  <BiasAckEditor
                    phrases={ackableSkills}
                    value={acks}
                    onChange={setAcks}
                    disabled={busy}
                  />
                </div>
              )}
              <p className="text-label-sm text-on-surface-variant">
                ถ้อยคำในประกาศไม่ได้ถูกใช้คิดคะแนน แต่ผู้สมัครจะเห็น ควรลบก่อนโพสต์ ถ้างานต้องการจริง
                กด “จำเป็นกับงานนี้” พร้อมเหตุผล · ข้อที่ไม่ยืนยันจะเตือนไว้ในหน้าผู้สมัครทุกคน
              </p>
              <button
                type="button"
                onClick={backToText}
                disabled={busy}
                className="text-label-md text-primary hover:underline"
              >
                กลับไปแก้ประกาศ
              </button>
            </div>
          )}
          {draft && !draft.bias.llm_checked && (
            <p className="text-label-sm text-on-surface-variant">
              ตรวจอคติด้วยกฎตายตัวอย่างเดียว — AI ตรวจไม่สำเร็จ
            </p>
          )}

          {draft?.warnings.map((w) => (
            <div
              key={w}
              role="note"
              className="flex gap-base items-start p-xs rounded-lg border border-tertiary/40 bg-tertiary-container/10"
            >
              <span
                className="material-symbols-outlined text-tertiary text-[18px] flex-none"
                style={{ fontVariationSettings: "'FILL' 1" }}
              >
                warning
              </span>
              <p className="text-label-md text-on-surface">{w}</p>
            </div>
          ))}
          {draft && draft.dropped.length > 0 && (
            <p className="text-label-sm text-on-surface">
              คัดออกเพราะไม่ใช่ทักษะ (เช่นชื่อบทบาท): {draft.dropped.join(", ")}
            </p>
          )}

          <div className="grid gap-sm sm:grid-cols-2">
            <label className="block space-y-xs sm:col-span-2">
              <span className="text-label-sm text-outline">ชื่อตำแหน่ง</span>
              <input
                className="input-glass w-full"
                value={title}
                maxLength={255}
                onChange={(e) => setTitle(e.target.value)}
                disabled={busy}
              />
            </label>
            <label className="block space-y-xs">
              <span className="text-label-sm text-outline">ประสบการณ์ขั้นต่ำ (ปี)</span>
              <input
                type="number"
                min={0}
                max={60}
                className="input-glass w-full"
                value={years}
                onChange={(e) => setYears(Math.max(0, Math.min(60, Number(e.target.value) || 0)))}
                disabled={busy}
              />
            </label>
            <label className="block space-y-xs">
              <span className="text-label-sm text-outline">การศึกษา</span>
              <input
                className="input-glass w-full"
                value={education}
                maxLength={500}
                onChange={(e) => setEducation(e.target.value)}
                placeholder="เช่น ปริญญาตรีสาขาคอมพิวเตอร์"
                disabled={busy}
              />
            </label>
          </div>

          <SkillListsEditor
            lists={lists}
            onChange={setLists}
            disabled={busy}
            sources={draft?.sources}
          />

          {skillWarning && (
            <div
              role="alert"
              className="flex items-start gap-xs p-sm rounded-xl border border-tertiary/50 bg-tertiary-container/15 text-label-md text-on-surface"
            >
              <span className="material-symbols-outlined text-tertiary text-[20px] flex-none" aria-hidden>
                gpp_maybe
              </span>
              <span>{skillWarning}</span>
            </div>
          )}

          <div className="flex flex-wrap items-center justify-end gap-xs pt-xs">
            <button
              type="button"
              className="btn-secondary-glass me-auto"
              onClick={backToText}
              disabled={busy}
              title="แก้ข้อความประกาศแล้ววิเคราะห์ใหม่ (ใช้ AI อีก 2 ครั้ง: ร่างเกณฑ์ + ตรวจอคติ)"
            >
              กลับไปแก้ประกาศ
            </button>
            <button
              type="button"
              className="btn-secondary-glass"
              onClick={() => router.push("/")}
              disabled={busy}
            >
              ยกเลิก
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={handleCreate}
              disabled={busy || !title.trim()}
            >
              {busy && <Spinner className="text-[18px]" />}
            {busy ? "กำลังบันทึก…" : "ยืนยันและสร้างตำแหน่ง"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
