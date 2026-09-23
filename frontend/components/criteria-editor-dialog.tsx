"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { previewCriteria, reanalyzeCriteria, saveCriteria } from "@/lib/api";
import SkillListsEditor from "@/components/skill-lists-editor";
import type { SkillLists } from "@/components/skill-lists-editor";
import { BANDS } from "@/lib/types";
import type { CriteriaPreview, CriteriaSaveResult, Job } from "@/lib/types";
import Spinner from "./spinner";

// รอให้หยุดกดสักครู่ก่อนยิง ลบ/ย้ายชิปติดกันหลายตัวจะได้เรียก backend ครั้งเดียว
const AUTO_PREVIEW_DELAY_MS = 400;

/**
 * โมดัลให้ HR ตรวจและแก้รายการทักษะที่ AI ดึงจาก JD
 *
 * ที่มา: AI ดึง "A, B, or C" เป็นข้อบังคับทุกตัว และเอาหน้าที่งานมาเป็นทักษะ คะแนนของทุกคน
 * จึงต่ำเกินจริง (memory-bank/06_scoring_criteria.md)
 *
 * ต้องมีผลกระทบของรายการปัจจุบันก่อนถึงบันทึกได้ — คำนวณให้เองทุกครั้งที่แก้ (เดิมมีช่องติ๊กปิดได้
 * แต่ไม่มีเหตุให้ใครปิด เอาออกให้เหลือตัวเลือกน้อยลง) พรีวิวไม่เรียก AI จึงยิงบ่อยได้โดยไม่เสียโควตา
 * — บันทึกแล้วคะแนนของผู้สมัครเดิม
 * ถูกคำนวณใหม่ทันที HR จึงควรเห็นก่อนว่าใครจะเปลี่ยนไปอย่างไร · คะแนนทุกตัวในตารางมาจาก
 * backend (สูตรเดียวกับกราฟ) ที่นี่ไม่คำนวณเอง
 */
export default function CriteriaEditorDialog({
  job,
  onSaved,
  onClose,
  onReanalyzed,
}: {
  job: Job;
  onSaved: (result: CriteriaSaveResult) => void;
  onClose: () => void;
  /** AI อ่านประกาศใหม่แล้ว — backend บันทึก ai_criteria ใหม่ หน้าแม่ควรดึง job ใหม่ */
  onReanalyzed?: () => void;
}) {
  const [lists, setLists] = useState<SkillLists>({
    required: job.parsed_criteria?.required_skills ?? [],
    preferred: job.parsed_criteria?.preferred_skills ?? [],
  });
  const [preview, setPreview] = useState<CriteriaPreview | null>(null);
  // รายการที่พรีวิวไว้ล่าสุด — แก้รายการหลังพรีวิวแล้วต้องพรีวิวใหม่ก่อนบันทึก
  const [previewedFor, setPreviewedFor] = useState<string | null>(null);
  const [busy, setBusy] = useState<"save" | "reanalyze" | null>(null);
  // รายการในหน้าต่างมาจากการให้ AI อ่านใหม่ และยังไม่ได้บันทึก — ให้ HR รู้ว่ายังต้องกดบันทึก
  const [reanalyzed, setReanalyzed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const current = JSON.stringify(lists);
  const previewFresh = preview !== null && previewedFor === current;
  // รายการล่าสุดที่ผู้ใช้เห็น ใช้ทิ้งผลพรีวิวที่กลับมาช้ากว่าการแก้ครั้งถัดไป
  const currentRef = useRef(current);
  currentRef.current = current;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  async function run<T>(
    kind: "save" | "reanalyze",
    fn: () => Promise<T>,
  ): Promise<T | null> {
    setBusy(kind);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "ทำรายการไม่สำเร็จ");
      return null;
    } finally {
      setBusy(null);
    }
  }

  function applyPreview(sentFor: string, r: CriteriaPreview) {
    // ผู้ใช้แก้ต่อระหว่างรอ → ผลนี้เก่าแล้ว ทิ้งไป (รอบถัดไปจะยิงให้เอง) ไม่งั้นจะเขียนทับการแก้ล่าสุด
    if (sentFor !== currentRef.current) return;
    // แสดงรายการที่ผ่านการทำความสะอาดแล้ว (ตัดซ้ำ/คำที่ไม่ใช่ทักษะ) ให้ตรงกับที่จะถูกบันทึก
    const cleaned = { required: r.required_skills, preferred: r.preferred_skills };
    setLists(cleaned);
    setPreview(r);
    setPreviewedFor(JSON.stringify(cleaned));
  }

  useEffect(() => {
    if (busy || previewedFor === current) return;
    const sentFor = current;
    // ไม่ผ่าน run()/busy: ระหว่างรอไม่ควรล็อกชิป ไม่งั้นลบหรือย้ายต่อเนื่องไม่ได้
    const timer = setTimeout(async () => {
      try {
        const r = await previewCriteria(job.id, {
          required_skills: lists.required,
          preferred_skills: lists.preferred,
        });
        setError(null);
        applyPreview(sentFor, r);
      } catch (e) {
        if (sentFor === currentRef.current) {
          setError(e instanceof Error ? e.message : "คำนวณผลกระทบไม่สำเร็จ");
        }
      }
    }, AUTO_PREVIEW_DELAY_MS);
    return () => clearTimeout(timer);
    // current (สตริงของ lists) บอกการเปลี่ยนของ lists อยู่แล้ว จึงไม่ต้องใส่ lists ใน deps
  }, [busy, current, previewedFor, job.id]);

  async function doSave() {
    const r = await run("save", () =>
      saveCriteria(job.id, {
        required_skills: lists.required,
        preferred_skills: lists.preferred,
      }),
    );
    if (r) onSaved(r);
  }

  async function doReanalyze() {
    const r = await run("reanalyze", () => reanalyzeCriteria(job.id));
    if (!r) return;
    // ผลที่ได้มาพร้อมผลกระทบแล้ว — ตั้งเป็นพรีวิวของรายการนี้ได้เลย ไม่ต้องยิงพรีวิวซ้ำ
    const next = { required: r.required_skills, preferred: r.preferred_skills };
    setLists(next);
    setPreview(r);
    setPreviewedFor(JSON.stringify(next));
    setReanalyzed(true);
    onReanalyzed?.();
  }

  const changed = preview?.impact.filter((i) => i.old_score !== i.new_score) ?? [];
  const bandChanged = changed.filter((i) => i.old_band !== i.new_band);

  if (typeof document === "undefined") return null;

  // portal ไป <body>: เนื้อหาหน้าอยู่ใน stacking context z-10 ของ app-shell
  // ถ้า render ในที่ แถบเมนูด้านข้าง (z-50) จะทับหัวโมดัล
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-md"
      role="dialog"
      aria-modal="true"
      aria-label="แก้ไขเกณฑ์ทักษะ"
    >
      <div
        className="absolute inset-0 bg-on-surface/30 backdrop-blur-sm"
        onClick={() => !busy && onClose()}
        aria-hidden
      />
      <div className="glass-card-elevated rounded-2xl p-md w-full max-w-3xl relative space-y-sm max-h-[90vh] overflow-y-auto">
        <h2 className="text-headline-md text-on-surface">แก้ไขเกณฑ์ทักษะ</h2>
        {/* text-on-surface ไม่ใช่ on-surface-variant: บนกระจกโมดัลในธีมมืดตัวหลังได้แค่ ~4.1:1 */}
        <p className="text-label-md text-on-surface">
          ทุกข้อในฝั่ง &ldquo;ต้องมี&rdquo; นับเป็นข้อบังคับ · ถ้ามีตัวใดตัวหนึ่งก็พอ ให้พิมพ์คั่นด้วย
          &ldquo;หรือ&rdquo; เช่น PyTorch หรือ TensorFlow (นับเป็น 1 ข้อ) · บันทึกแล้วคะแนนผู้สมัครเดิม
          คำนวณใหม่ทันที โดยไม่เรียก AI
        </p>

        <SkillListsEditor lists={lists} onChange={setLists} disabled={!!busy} />

        {preview && (
          <section
            className={`space-y-xs transition-opacity ${previewFresh ? "" : "opacity-50"}`}
            aria-live="polite"
            aria-busy={!previewFresh}
          >
            {!previewFresh && (
              <p className="text-label-sm font-semibold text-on-surface">
                กำลังอัปเดตผลกระทบ…
              </p>
            )}
            {preview.warnings.map((w) => (
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
            {preview.dropped.length > 0 && (
              <p className="text-label-sm text-on-surface">
                คัดออกเพราะไม่ใช่ทักษะ (เช่นชื่อบทบาท): {preview.dropped.join(", ")}
              </p>
            )}

            <p className="text-label-md font-semibold text-on-surface">
              ผลกระทบ: คะแนนเปลี่ยน {changed.length} จาก {preview.impact.length} คน · เปลี่ยนแบนด์{" "}
              {bandChanged.length} คน
            </p>
            {preview.impact.length > 0 && (
              <div className="overflow-x-auto rounded-xl border border-outline-variant/40">
                <table className="w-full text-label-md">
                  <thead className="bg-surface-container-high/60 text-on-surface text-label-sm">
                    <tr>
                      <th className="text-start px-xs py-1.5 font-semibold">ผู้สมัคร</th>
                      <th className="text-end px-xs py-1.5 font-semibold">เดิม</th>
                      <th className="text-end px-xs py-1.5 font-semibold">ใหม่</th>
                      <th className="text-start px-xs py-1.5 font-semibold">หมายเหตุ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.impact.map((i) => {
                      const moved = i.old_band !== i.new_band;
                      return (
                        <tr key={i.candidate_id} className="border-t border-outline-variant/30">
                          <td className="px-xs py-1.5 text-on-surface">{i.full_name}</td>
                          <td className="px-xs py-1.5 text-end tabular-nums text-on-surface">
                            {i.old_score}
                          </td>
                          <td className="px-xs py-1.5 text-end">
                            <span
                              className={`inline-block tabular-nums text-[12px] font-semibold px-2 py-0.5 rounded-full ${BANDS[i.new_band].chip}`}
                            >
                              {i.new_score}
                            </span>
                          </td>
                          <td className="px-xs py-1.5 text-label-sm text-on-surface">
                            {[
                              moved && `${BANDS[i.old_band].label} → ${BANDS[i.new_band].label}`,
                              i.hr_decision && i.hr_decision !== "pending" && "HR ตัดสินแล้ว",
                              i.email_sent && "ส่งอีเมลแล้ว",
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {bandChanged.length > 0 && (
              <p className="text-label-sm text-on-surface">
                คนที่เปลี่ยนแบนด์จะขึ้นป้าย &ldquo;ตรวจอีกครั้ง&rdquo; ระบบไม่ส่งอีเมล ไม่ลบร่างเดิม
                และไม่เปลี่ยนคำตัดสินให้เอง
              </p>
            )}
          </section>
        )}

        {reanalyzed && (
          <p
            role="status"
            className="flex gap-base items-start p-xs rounded-lg border border-primary/40 bg-primary-container/10 text-label-md text-on-surface"
          >
            <span className="material-symbols-outlined text-primary text-[18px] flex-none">
              auto_awesome
            </span>
            AI อ่านประกาศใหม่แล้ว ยังไม่ได้บันทึก — ตรวจรายการและผลกระทบ แล้วกด
            &ldquo;บันทึกและคำนวณใหม่&rdquo; หรือปิดหน้าต่างถ้าไม่ต้องการ
          </p>
        )}

        {error && (
          <p className="text-error text-label-md" role="alert">
            {error}
          </p>
        )}

        <div className="flex flex-wrap items-center justify-end gap-xs pt-xs">
          <div className="flex flex-wrap gap-xs me-auto">
            <button
              type="button"
              className="btn-secondary-glass inline-flex items-center gap-1.5"
              onClick={doReanalyze}
              disabled={!!busy}
              title="อ่านประกาศของตำแหน่งนี้ใหม่ด้วยวิธีล่าสุด (ใช้ AI 1 ครั้ง) — ยังไม่บันทึกจนกว่าจะกดบันทึก"
            >
              {busy === "reanalyze" ? (
                <Spinner className="text-[16px]" />
              ) : (
                <span className="material-symbols-outlined text-[16px]">auto_awesome</span>
              )}
              {busy === "reanalyze" ? "AI กำลังอ่านประกาศ…" : "ให้ AI อ่านประกาศใหม่"}
            </button>
          </div>
          <button type="button" className="btn-secondary-glass" onClick={onClose} disabled={!!busy}>
            ปิด
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={doSave}
            disabled={!!busy || !previewFresh}
            title={previewFresh ? undefined : "รอผลกระทบของรายการปัจจุบันสักครู่"}
          >
            {busy === "save" && <Spinner className="text-[18px]" />}
            {busy === "save" ? "กำลังบันทึก…" : "บันทึกและคำนวณใหม่"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
