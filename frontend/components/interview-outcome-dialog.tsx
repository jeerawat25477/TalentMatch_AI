"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { saveInterviewOutcome } from "@/lib/api";
import { INTERVIEW_RESULT, normalizeQuestions } from "@/lib/types";
import Spinner from "./spinner";
import type {
  InterviewOutcome,
  InterviewPlan,
  InterviewResult,
  QuestionScore,
} from "@/lib/types";

// วันที่วันนี้ (YYYY-MM-DD) สำหรับ <input type="date">
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

const SCORES = [1, 2, 3, 4, 5];
const RESULT_ORDER: InterviewResult[] = ["pass", "standby", "fail"];

/**
 * ฟอร์มบันทึกผลสัมภาษณ์จริง — คำถามมาจากแผนที่ AI ร่างไว้แล้ว HR ให้คะแนนรายข้อ
 *
 * เป็นโมดัล ไม่ใช่ฟอร์มฝังในหน้า เพราะหน้า deep dive poll ทุก 4 วินาที: state ที่อยู่
 * ในหน้าจะถูกรีเฟรชทับสิ่งที่ HR กำลังพิมพ์ ส่วนโมดัล seed ครั้งเดียวตอน mount
 *
 * ⚠️ บันทึกผลไม่ใช่การตัดสินคัดกรอง — endpoint นี้ไม่แตะ hr_decision และไม่ปลุกกราฟ
 */
export default function InterviewOutcomeDialog({
  candidateId,
  plan,
  existing,
  onSaved,
  onClose,
}: {
  candidateId: string;
  plan: InterviewPlan | null;
  existing: InterviewOutcome | null;
  onSaved: () => void;
  onClose: () => void;
}) {
  // seed ครั้งเดียวตอน mount: คำถามจากแผน + คะแนน/โน้ตเดิมถ้าเคยบันทึกไว้
  const [rows, setRows] = useState<QuestionScore[]>(() => {
    // จับคู่ด้วย "ข้อความคำถาม" ไม่ใช่ index — ผู้สมัครที่ถูก reprocess จะได้แผนชุดใหม่
    // ที่ลำดับไม่ตรงของเดิม การจับคู่ด้วยตำแหน่งจะเอาคะแนนไปแปะผิดข้อแบบเงียบ ๆ
    const saved = new Map(
      (existing?.question_scores ?? []).map((q) => [q.question, q]),
    );
    return normalizeQuestions(plan).map((q) => {
      const prev = saved.get(q.question);
      return {
        question: q.question,
        score: prev?.score ?? null,
        note: prev?.note ?? null,
      };
    });
  });
  const [result, setResult] = useState<InterviewResult | null>(
    existing?.result ?? null,
  );
  const [overallNote, setOverallNote] = useState(existing?.overall_note ?? "");
  const [date, setDate] = useState(existing?.interviewed_at ?? today());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // ไม่ปิดระหว่างกำลังบันทึก — กันกด Esc หนีระหว่างที่รีเควสต์ยังค้างอยู่
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  function setRow(i: number, patch: Partial<QuestionScore>) {
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  }

  async function submit() {
    if (!result) return;
    setBusy(true);
    setError(null);
    try {
      await saveInterviewOutcome(candidateId, {
        result,
        question_scores: rows,
        overall_note: overallNote.trim() || null,
        interviewed_at: date || null,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "บันทึกผลสัมภาษณ์ไม่สำเร็จ");
      setBusy(false);
    }
  }

  // ⚠️ ต้อง portal ไปที่ <body> ไม่ใช่ render ในที่: เนื้อหาของทุกหน้าอยู่ในกล่อง
  // `relative z-10` ของ app-shell ซึ่งเป็น stacking context — โมดัลที่เกิดข้างในนั้น
  // ถูกเพดาน z=10 กดไว้ แล้วแถบเมนูด้านข้าง (fixed z-50) ทับทับหัวโมดัลเสมอ
  // ไม่ว่าจะใส่ z เท่าไรข้างใน · โมดัลเดิมสองตัวไม่เจอเพราะกว้างแค่ max-w-lg จึงพอดี
  // หลบพ้นแถบเมนูที่จอ 1024px ขึ้นไป (ที่แคบกว่านั้นทับเหมือนกัน)
  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-md"
      role="dialog"
      aria-modal="true"
      aria-label="บันทึกผลสัมภาษณ์"
    >
      <div
        className="absolute inset-0 bg-on-surface/30 backdrop-blur-sm"
        onClick={() => !busy && onClose()}
        aria-hidden
      />

      <div className="glass-card-elevated rounded-2xl p-md w-full max-w-2xl relative space-y-sm max-h-[90vh] overflow-y-auto">
        <h2 className="text-headline-md text-on-surface">บันทึกผลสัมภาษณ์</h2>
        <p className="text-label-md text-on-surface-variant">
          ให้คะแนนรายข้อจากคำถามที่ระบบร่างไว้ แล้วสรุปผลรวม — ข้อมูลนี้ใช้วัดความแม่นของ
          คะแนนคัดกรองในระยะยาว ไม่ได้เปลี่ยนคำตัดสินคัดกรองที่บันทึกไว้แล้ว
        </p>

        {/* ---- คะแนนรายข้อ ---- */}
        <div className="space-y-xs">
          {rows.map((r, i) => (
            <div
              key={i}
              className="rounded-xl border border-outline-variant/40 p-sm space-y-xs"
            >
              <div className="flex gap-xs">
                <span className="flex-none w-6 h-6 rounded-full bg-primary/10 text-primary text-label-sm flex items-center justify-center mt-0.5">
                  {i + 1}
                </span>
                <p className="text-body-md text-on-surface min-w-0 flex-1">
                  {r.question}
                </p>
              </div>

              <div
                className="flex items-center gap-base flex-wrap ps-8"
                role="group"
                aria-label={`คะแนนข้อ ${i + 1}`}
              >
                {SCORES.map((n) => (
                  <button
                    key={n}
                    type="button"
                    // ปุ่มจริง ไม่ใช่ div ที่ผูก onClick — คีย์บอร์ดกับสกรีนรีดเดอร์ใช้ได้ฟรี
                    aria-pressed={r.score === n}
                    disabled={busy}
                    // กดปุ่มเดิมซ้ำ = ล้างคะแนน (ไม่ได้ถามข้อนี้ ต่างจากถามแล้วได้ 1)
                    onClick={() => setRow(i, { score: r.score === n ? null : n })}
                    className={`w-8 h-8 rounded-lg text-label-md font-semibold transition-colors ${
                      r.score === n
                        ? "bg-primary text-on-primary"
                        : "bg-surface-container-high text-on-surface-variant hover:bg-primary-container/30"
                    }`}
                  >
                    {n}
                  </button>
                ))}
                <span className="text-label-sm text-outline ms-xs">
                  {r.score === null ? "ยังไม่ให้คะแนน" : "จาก 5"}
                </span>
              </div>

              <label className="block ps-8">
                <span className="sr-only">โน้ตข้อ {i + 1}</span>
                <input
                  className="input-glass w-full text-label-md"
                  placeholder="โน้ตคำตอบที่ได้ (ไม่บังคับ)"
                  value={r.note ?? ""}
                  onChange={(e) => setRow(i, { note: e.target.value || null })}
                  disabled={busy}
                />
              </label>
            </div>
          ))}
        </div>

        {/* ---- ผลรวม ---- */}
        <div className="grid gap-sm sm:grid-cols-2">
          <div className="space-y-xs">
            <span className="text-label-sm text-outline">ผลรวม</span>
            <div className="flex gap-base" role="group" aria-label="ผลสัมภาษณ์รวม">
              {RESULT_ORDER.map((k) => (
                <button
                  key={k}
                  type="button"
                  aria-pressed={result === k}
                  disabled={busy}
                  onClick={() => setResult(k)}
                  className={`px-sm py-1.5 rounded-lg text-label-md font-semibold transition-colors inline-flex items-center gap-base ${
                    result === k
                      ? INTERVIEW_RESULT[k].chip
                      : "bg-surface-container-high text-on-surface-variant hover:bg-primary-container/30"
                  }`}
                >
                  <span className="material-symbols-outlined text-[18px]">
                    {INTERVIEW_RESULT[k].icon}
                  </span>
                  {INTERVIEW_RESULT[k].label}
                </button>
              ))}
            </div>
          </div>

          <label className="block space-y-xs">
            <span className="text-label-sm text-outline">วันที่สัมภาษณ์</span>
            <input
              type="date"
              className="input-glass w-full"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              disabled={busy}
            />
          </label>
        </div>

        <label className="block space-y-xs">
          <span className="text-label-sm text-outline">สรุปรวม</span>
          <textarea
            className="input-glass w-full"
            rows={3}
            placeholder="ความเห็นโดยรวม จุดแข็ง จุดที่ยังกังวล (ไม่บังคับ)"
            value={overallNote}
            onChange={(e) => setOverallNote(e.target.value)}
            disabled={busy}
          />
        </label>

        {error && (
          <p className="text-error text-label-md" role="alert">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-xs pt-xs">
          <button
            className="btn-secondary-glass"
            onClick={onClose}
            disabled={busy}
          >
            ยกเลิก
          </button>
          <button className="btn-primary" onClick={submit} disabled={busy || !result}>
            {busy && <Spinner className="text-[18px]" />}
            {busy ? "กำลังบันทึก…" : "บันทึกผล"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
