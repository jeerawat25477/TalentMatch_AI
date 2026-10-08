"use client";

import { useState } from "react";
import ConfirmDialog from "@/components/confirm-dialog";
import Spinner from "@/components/spinner";
import { biasedSkillErrorOf, previewCriteria, updateBiasAcks } from "@/lib/api";
import {
  BIAS_ACK_MIN_REASON,
  type BiasAck,
  type BiasAckIn,
  type CriteriaImpact,
  type Job,
  type JobBiasView,
} from "@/lib/types";

/**
 * HR ยืนยันว่าถ้อยคำที่ตัวตรวจอคติเตือน "จำเป็นกับงานนี้จริง" (เช่น เพศหญิงสำหรับงานตรวจค้นตัว)
 *
 * ยืนยันทีละถ้อยคำ ต้องมีเหตุผล และบันทึกว่าใคร/เมื่อไร (ฝั่ง backend) · ปกติไม่มีผลกับคะแนน —
 * เปลี่ยนแค่สิ่งที่ HR เห็นในหน้าผู้สมัคร ไม่ให้คำเตือนเรื่องที่ตัดสินแล้วขึ้นซ้ำทุกคนจนคนเลิกอ่าน
 * ยกเว้นถ้อยคำที่ HR ใส่เป็นทักษะในเกณฑ์ด้วย (scored): ยืนยันแล้วจึงนับคะแนน และถอนไม่ได้จนกว่าจะลบทักษะ
 */

/** phrase → เหตุผล (มีคีย์ = ยืนยันแล้ว) */
export type AckMap = Record<string, string>;

export const toAckIn = (m: AckMap): BiasAckIn[] =>
  Object.entries(m).map(([phrase, reason]) => ({ phrase, reason }));

export const fromAcks = (acks: BiasAck[]): AckMap =>
  Object.fromEntries(acks.map((a) => [a.phrase, a.reason]));

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString("th-TH", { day: "numeric", month: "short", year: "2-digit" });

/** รายการถ้อยคำพร้อมปุ่ม "จำเป็นกับงานนี้" — controlled ใช้ได้ทั้งขั้นยืนยันเกณฑ์และหน้าตำแหน่ง */
export function BiasAckEditor({
  phrases,
  value,
  onChange,
  saved = [],
  disabled,
}: {
  phrases: string[];
  value: AckMap;
  onChange: (next: AckMap) => void;
  /** การยืนยันที่บันทึกแล้ว — ใช้โชว์ว่าใคร/เมื่อไร */
  saved?: BiasAck[];
  disabled?: boolean;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const meta = Object.fromEntries(saved.map((a) => [a.phrase, a]));

  function confirm(phrase: string) {
    onChange({ ...value, [phrase]: draft.trim() });
    setOpen(null);
    setDraft("");
  }

  function withdraw(phrase: string) {
    const next = { ...value };
    delete next[phrase];
    onChange(next);
  }

  return (
    <ul className="space-y-xs">
      {phrases.map((p) => {
        const reason = value[p];
        const m = meta[p];
        return (
          <li key={p} className="rounded-lg border border-outline-variant/40 p-xs space-y-1">
            <div className="flex flex-wrap items-center gap-xs">
              <span className="text-label-md font-semibold text-on-surface">“{p}”</span>
              {reason !== undefined ? (
                <>
                  <span className="inline-flex items-center gap-0.5 text-label-sm text-on-surface-variant">
                    <span className="material-symbols-outlined text-[16px]" aria-hidden>
                      task_alt
                    </span>
                    HR ยืนยันว่าจำเป็น
                  </span>
                  {m?.scored && (
                    <span
                      title="ถ้อยคำนี้ใส่ไว้เป็นทักษะในเกณฑ์ด้วย — ถอนได้หลังลบทักษะออกจากเกณฑ์"
                      className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-primary-fixed text-on-primary-fixed-variant"
                    >
                      นับเป็นทักษะในคะแนน
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => withdraw(p)}
                    disabled={disabled}
                    className="ms-auto text-label-sm text-primary hover:underline"
                  >
                    ถอน
                  </button>
                </>
              ) : (
                open !== p && (
                  <button
                    type="button"
                    onClick={() => {
                      setOpen(p);
                      setDraft("");
                    }}
                    disabled={disabled}
                    className="ms-auto text-label-sm text-primary hover:underline"
                  >
                    จำเป็นกับงานนี้
                  </button>
                )
              )}
            </div>

            {reason !== undefined && (
              <p className="text-label-sm text-on-surface-variant">
                {reason}
                {m && m.reason === reason && (
                  <span className="text-outline"> — {m.by}, {fmtDate(m.at)}</span>
                )}
              </p>
            )}

            {open === p && (
              <div className="space-y-1">
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  rows={2}
                  maxLength={500}
                  placeholder="ทำไมงานนี้ต้องการ เช่น กฎหมายกำหนด หรือลักษณะงานทำแทนไม่ได้"
                  className="input-glass w-full resize-y text-label-md"
                  autoFocus
                />
                <div className="flex items-center justify-end gap-xs">
                  <span className="text-label-sm text-outline me-auto">
                    อย่างน้อย {BIAS_ACK_MIN_REASON} ตัวอักษร
                  </span>
                  <button
                    type="button"
                    className="btn-secondary-glass text-label-sm py-1"
                    onClick={() => setOpen(null)}
                  >
                    ยกเลิก
                  </button>
                  <button
                    type="button"
                    className="btn-primary text-label-sm py-1 disabled:opacity-50"
                    disabled={draft.trim().length < BIAS_ACK_MIN_REASON}
                    onClick={() => confirm(p)}
                  >
                    ยืนยัน
                  </button>
                </div>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** การ์ดในหน้าตำแหน่ง — ยืนยัน/ถอนถ้อยคำของตำแหน่งที่สร้างไปแล้ว */
export function JobBiasCard({ job, onSaved }: { job: Job; onSaved: (j: Job) => void }) {
  const bias = job.bias;
  const initial = fromAcks(bias?.acknowledged ?? []);
  const [value, setValue] = useState<AckMap>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // ถอนถ้อยคำที่ยังเป็นทักษะในเกณฑ์ → ถามก่อนพร้อมผลกระทบ แล้วลบทักษะ + คำนวณคะแนนใหม่ในคราวเดียว
  const [removal, setRemoval] = useState<{ skills: string[]; impact: CriteriaImpact[] } | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  if (!bias) return null;
  const phrases = [...bias.acknowledged.map((a) => a.phrase), ...bias.pending];
  if (phrases.length === 0 && bias.biased_skills.length === 0) return null;

  const dirty = JSON.stringify(value) !== JSON.stringify(initial);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      onSaved(await updateBiasAcks(job.id, toAckIn(value)));
    } catch (e) {
      const biased = biasedSkillErrorOf(e);
      if (biased?.stripped) {
        // backend บอกเกณฑ์หลังลบทักษะมาแล้ว — พรีวิวผลกระทบ (ไม่เขียนอะไร) ให้ HR เห็นก่อนยืนยัน
        try {
          const preview = await previewCriteria(job.id, biased.stripped);
          setRemoveError(null);
          setRemoval({ skills: biased.skills.map((s) => s.skill), impact: preview.impact });
        } catch (pe) {
          setError(pe instanceof Error ? pe.message : "คำนวณผลกระทบไม่สำเร็จ");
        }
      } else {
        setError(biased?.message ?? (e instanceof Error ? e.message : "บันทึกไม่สำเร็จ"));
      }
    } finally {
      setBusy(false);
    }
  }

  async function confirmRemoval() {
    setBusy(true);
    setRemoveError(null);
    try {
      onSaved(await updateBiasAcks(job.id, toAckIn(value), true));
      setRemoval(null);
    } catch (e) {
      setRemoveError(e instanceof Error ? e.message : "บันทึกไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  const changed = removal?.impact.filter((i) => i.old_score !== i.new_score).length ?? 0;
  const crossed = removal?.impact.filter((i) => i.old_band !== i.new_band).length ?? 0;

  return (
    <section className="glass-card rounded-2xl p-md space-y-sm">
      <div>
        <h3 className="text-label-md font-bold text-on-surface flex items-center gap-xs">
          <span className="material-symbols-outlined text-tertiary text-[20px]" aria-hidden>
            gpp_maybe
          </span>
          ถ้อยคำในประกาศที่อาจมีอคติ
        </h3>
        <p className="text-label-sm text-on-surface-variant">
          ถ้างานนี้ต้องการจริง กด “จำเป็นกับงานนี้” พร้อมเหตุผล — คำเตือนในหน้าผู้สมัครจะเปลี่ยนเป็นบันทึกการยืนยันแทน
          · ถ้อยคำในประกาศไม่ได้ใช้คิดคะแนน ยกเว้นข้อที่ใส่เป็นทักษะในเกณฑ์ด้วย
        </p>
      </div>

      {phrases.length > 0 && (
        <BiasAckEditor
          phrases={phrases}
          value={value}
          onChange={setValue}
          saved={bias.acknowledged}
          disabled={busy}
        />
      )}
      {bias.biased_skills.length > 0 && (
        <p className="text-label-sm text-on-surface">
          เกณฑ์ทักษะที่อาจมีอคติ: {bias.biased_skills.join(", ")} — แก้ได้ที่ปุ่มแก้เกณฑ์
        </p>
      )}

      {error && (
        <p className="text-error text-label-sm" role="alert">
          {error}
        </p>
      )}
      {dirty && (
        <div className="flex justify-end gap-xs">
          <button
            type="button"
            className="btn-secondary-glass"
            onClick={() => setValue(initial)}
            disabled={busy}
          >
            ยกเลิก
          </button>
          <button type="button" className="btn-primary" onClick={save} disabled={busy}>
            {busy && <Spinner className="text-[18px]" />}
            บันทึก
          </button>
        </div>
      )}

      {removal && (
        <ConfirmDialog
          title="ถอนการยืนยันและลบออกจากเกณฑ์คะแนน"
          body={
            <div className="space-y-xs">
              <p>
                {removal.skills.map((s) => `“${s}”`).join(", ")} ยังเป็นทักษะในเกณฑ์คะแนน
                ถ้าถอนการยืนยัน ระบบจะลบออกจากเกณฑ์และคำนวณคะแนนใหม่ให้ด้วย
              </p>
              <p className="text-on-surface-variant">
                {removal.impact.length === 0
                  ? "ตำแหน่งนี้ยังไม่มีผู้สมัคร จึงไม่มีคะแนนใครเปลี่ยน"
                  : `คะแนนผู้สมัครเปลี่ยน ${changed} จาก ${removal.impact.length} คน` +
                    (crossed > 0 ? ` · ${crossed} คนเปลี่ยนกลุ่ม (ควรทบทวนการตัดสินใจ)` : "")}
              </p>
            </div>
          }
          confirmLabel="ถอนและลบออกจากเกณฑ์"
          busy={busy}
          error={removeError}
          onConfirm={confirmRemoval}
          onClose={() => setRemoval(null)}
        />
      )}
    </section>
  );
}

/** กล่องผลตรวจอคติในหน้าผู้สมัคร — อ่านจากตำแหน่งสด ๆ */
export function CandidateBiasBox({ bias }: { bias: JobBiasView }) {
  const flagged = bias.status === "flagged";
  return (
    <div className="p-sm rounded-xl border border-secondary/20 bg-secondary-container/10 space-y-xs">
      <div className="flex gap-xs items-start">
        <span
          className={`material-symbols-outlined ${flagged ? "text-tertiary" : "text-secondary"}`}
          style={{ fontVariationSettings: "'FILL' 1" }}
          aria-hidden
        >
          {flagged ? "gpp_maybe" : "verified_user"}
        </span>
        <div className="min-w-0 space-y-1">
          {flagged ? (
            <>
              <p className="text-on-surface text-label-md leading-snug">{bias.summary}</p>
              {bias.pending.length > 0 && (
                <p className="text-label-sm text-on-surface">
                  ⚠ ถ้อยคำในประกาศที่อาจมีอคติ (ไม่ได้ถูกใช้คิดคะแนน):{" "}
                  {bias.pending.map((p) => `“${p}”`).join(", ")}
                </p>
              )}
              {bias.biased_skills.length > 0 && (
                <p className="text-label-sm text-on-surface">
                  เกณฑ์ทักษะที่อาจมีอคติ: {bias.biased_skills.join(", ")}
                </p>
              )}
            </>
          ) : (
            <p className="text-on-surface text-label-md leading-snug">
              {bias.acknowledged.length > 0
                ? "ไม่มีคำเตือนค้าง — ถ้อยคำที่ตัวตรวจพบ HR ยืนยันแล้วว่าจำเป็นกับงานนี้"
                : bias.summary}
            </p>
          )}
          <p className={`font-bold text-label-sm ${flagged ? "text-tertiary" : "text-secondary"}`}>
            {flagged ? "พบสัญญาณอคติ — ทบทวนอีกครั้ง" : "ผ่านเกณฑ์ความโปร่งใส"}
          </p>
        </div>
      </div>

      {bias.acknowledged.length > 0 && (
        <ul className="border-t border-outline-variant/30 pt-xs space-y-1">
          {bias.acknowledged.map((a) => (
            <li key={a.phrase} className="text-label-sm text-on-surface-variant">
              <span className="text-on-surface font-semibold">“{a.phrase}”</span> — HR ยืนยันว่าจำเป็น
              {a.scored && " (นับเป็นทักษะในคะแนน)"}:{" "}
              {a.reason} <span className="text-outline">({a.by}, {fmtDate(a.at)})</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
