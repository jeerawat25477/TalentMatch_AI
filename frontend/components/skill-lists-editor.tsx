"use client";

import { useState } from "react";
import { skillLabel, splitSkillInput } from "@/lib/skill-group";

export type Side = "required" | "preferred";
export type SkillLists = Record<Side, string[]>;

export const SIDE_LABEL: Record<Side, string> = {
  required: "ทักษะที่ต้องมี",
  preferred: "ทักษะที่อยากได้",
};

/**
 * สองกล่องแก้รายการทักษะ (เพิ่ม/ลบ/ย้ายฝั่ง) — ใช้ร่วมกันสองที่:
 * หน้าต่างแก้เกณฑ์ของตำแหน่งที่มีอยู่ และขั้นยืนยันเกณฑ์ตอนสร้างตำแหน่งใหม่
 * แยกออกมาเพื่อไม่ให้มีสองสำเนาที่ค่อย ๆ ต่างกัน
 *
 * `sources` = ทักษะข้อนั้นมาจากบรรทัดไหนในประกาศ (backend ส่งมาตอนวิเคราะห์) กดที่ชื่อทักษะ
 * เพื่อดู — ทำให้ HR ตอบได้ว่าทำไมข้อนี้ถึงอยู่ฝั่งนี้ ไม่ต้องเดา
 */
export default function SkillListsEditor({
  lists,
  onChange,
  disabled = false,
  sources,
}: {
  lists: SkillLists;
  onChange: (next: SkillLists) => void;
  disabled?: boolean;
  sources?: Record<string, string[]>;
}) {
  const [drafts, setDrafts] = useState<Record<Side, string>>({ required: "", preferred: "" });
  const [openSource, setOpenSource] = useState<string | null>(null);

  function add(side: Side) {
    const items = splitSkillInput(drafts[side]);
    if (!items.length) return;
    onChange({ ...lists, [side]: [...lists[side], ...items] });
    setDrafts((d) => ({ ...d, [side]: "" }));
  }

  function remove(side: Side, i: number) {
    onChange({ ...lists, [side]: lists[side].filter((_, j) => j !== i) });
  }

  function move(from: Side, i: number) {
    const to: Side = from === "required" ? "preferred" : "required";
    onChange({
      ...lists,
      [from]: lists[from].filter((_, j) => j !== i),
      [to]: [...lists[to], lists[from][i]],
    });
  }

  return (
    <div className="grid gap-sm md:grid-cols-2">
      {(["required", "preferred"] as Side[]).map((side) => (
        <section
          key={side}
          className="rounded-xl border border-outline-variant/40 p-sm space-y-xs"
          aria-label={SIDE_LABEL[side]}
        >
          <h3 className="text-label-md font-semibold text-on-surface">
            {SIDE_LABEL[side]}{" "}
            <span className="text-on-surface font-normal tabular-nums">
              ({lists[side].length})
            </span>
          </h3>
          <ul className="flex flex-wrap gap-base">
            {lists[side].map((s, i) => {
              const from = sources?.[s];
              return (
                <li
                  key={`${s}-${i}`}
                  className={`inline-flex items-center gap-0.5 text-[12px] font-semibold ps-2.5 pe-1 py-0.5 rounded-full ${
                    side === "required"
                      ? "bg-primary-fixed text-on-primary-fixed-variant"
                      : "bg-surface-container-high text-on-surface-variant"
                  }`}
                >
                  {from ? (
                    <button
                      type="button"
                      onClick={() => setOpenSource(openSource === s ? null : s)}
                      className="underline decoration-dotted underline-offset-2"
                      title="ดูว่ามาจากบรรทัดไหนในประกาศ"
                      aria-expanded={openSource === s}
                    >
                      {skillLabel(s)}
                    </button>
                  ) : (
                    skillLabel(s)
                  )}
                  <button
                    type="button"
                    onClick={() => move(side, i)}
                    disabled={disabled}
                    className="w-6 h-6 rounded-full inline-flex items-center justify-center hover:bg-on-surface/10"
                    aria-label={`ย้าย ${skillLabel(s)} ไป${side === "required" ? SIDE_LABEL.preferred : SIDE_LABEL.required}`}
                    title={`ย้ายไป${side === "required" ? SIDE_LABEL.preferred : SIDE_LABEL.required}`}
                  >
                    <span className="material-symbols-outlined text-[16px]">
                      {side === "required" ? "arrow_forward" : "arrow_back"}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(side, i)}
                    disabled={disabled}
                    className="w-6 h-6 rounded-full inline-flex items-center justify-center hover:bg-on-surface/10"
                    aria-label={`ลบ ${skillLabel(s)}`}
                    title="ลบ"
                  >
                    <span className="material-symbols-outlined text-[16px]">close</span>
                  </button>
                </li>
              );
            })}
            {lists[side].length === 0 && (
              <li className="text-label-sm text-on-surface">ยังไม่มี</li>
            )}
          </ul>

          {/* ที่มาของข้อที่กดค้างไว้ — โชว์ในฝั่งที่ข้อนั้นอยู่ */}
          {openSource && lists[side].includes(openSource) && (
            <p className="text-label-sm text-on-surface-variant border-s-2 border-primary/40 ps-xs">
              มาจากประกาศบรรทัด:{" "}
              {(sources?.[openSource] ?? []).map((line) => (
                <span key={line} className="block break-words">
                  “{line}”
                </span>
              ))}
            </p>
          )}

          <div className="flex gap-base">
            <label className="flex-1 min-w-0">
              <span className="sr-only">เพิ่ม{SIDE_LABEL[side]}</span>
              <input
                className="input-glass w-full text-label-md"
                placeholder="พิมพ์แล้วกด Enter (คั่นหลายตัวด้วยจุลภาค)"
                value={drafts[side]}
                maxLength={500}
                onChange={(e) => setDrafts((d) => ({ ...d, [side]: e.target.value }))}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    add(side);
                  }
                }}
                disabled={disabled}
              />
            </label>
            <button
              type="button"
              className="btn-secondary-glass"
              onClick={() => add(side)}
              disabled={disabled || !drafts[side].trim()}
            >
              เพิ่ม
            </button>
          </div>
        </section>
      ))}
    </div>
  );
}
