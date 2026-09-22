"use client";

import { useId, useState } from "react";
import { skillLabel } from "@/lib/skill-group";
import type { SkillGapCount, SkillGapStats } from "@/lib/types";

/**
 * ทักษะที่ผู้สมัครในตำแหน่งนี้ขาดบ่อยที่สุด — อยู่ท้ายการ์ดฮิสโตแกรมคะแนน แบบพับไว้
 * ฮิสโตแกรมบอก "คะแนนรวมเป็นยังไง" ส่วนอันนี้บอก "ทำไม — ขาดอะไรกันบ่อย"
 * พับไว้เป็นค่าตั้งต้นให้หน้าไม่ยาว ปุ่มโชว์ทักษะที่ขาดมากสุดไว้ให้รู้ก่อนว่าข้างในมีอะไร
 *
 * แยกสองกลุ่มไม่ปนกัน: ขาดของที่ต้องมี (หักคะแนนหนักกว่า) กับขาดของที่อยากได้
 * สี: ต้องมีใช้โทน error เดียวกับแผง "ทักษะที่ยังขาด" ใน skill-gap.tsx · อยากได้ใช้ tertiary
 * (skill-gap.tsx ไม่มีโทนเหลือง และเหลืองอำพันของแบนด์สงวนไว้ให้คะแนนเท่านั้น)
 *
 * ความยาวแท่ง = ขาดกี่คน ÷ ผู้สมัครที่มีผลทั้งหมด — 100% แปลว่าขาดทุกคน ซึ่งมักแปลว่าเกณฑ์นั้น
 * อาจเข้มเกินไปหรือ AI ดึงมาผิด ควรลองดูเกณฑ์อีกครั้ง
 */
export function SkillGapDisclosure({ data }: { data: SkillGapStats }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const total = data.total_candidates;
  // ยังไม่มีใครมีผล ฮิสโตแกรมบอกไว้แล้วข้างบน ไม่ต้องมีปุ่มที่กดแล้วว่างเปล่า
  if (total === 0) return null;

  const worst = [...data.required, ...data.preferred].sort(
    (a, b) => b.missing_count - a.missing_count,
  )[0];

  return (
    <div className="mt-sm pt-sm border-t border-outline-variant/40">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="w-full flex items-center gap-xs text-left rounded-lg px-xs py-1 -mx-xs hover:bg-glass/40 transition-colors"
      >
        <span className="material-symbols-outlined text-primary text-[20px]" aria-hidden>
          troubleshoot
        </span>
        <span className="flex-1 min-w-0">
          <span className="text-label-md font-semibold text-on-surface">ทักษะที่ขาดบ่อย</span>
          {!open && worst && (
            <span className="text-label-sm text-on-surface-variant">
              {" "}· มากสุด {skillLabel(worst.skill)} ขาด {worst.missing_count} จาก {total} คน
            </span>
          )}
        </span>
        <span className="flex-none text-label-sm text-primary">
          {open ? "ซ่อน" : "ดูเพิ่มเติม"}
        </span>
        <span
          className={`material-symbols-outlined text-primary text-[20px] transition-transform ${
            open ? "rotate-180" : ""
          }`}
          aria-hidden
        >
          expand_more
        </span>
      </button>

      {open && (
        <div id={panelId} className="mt-sm">
          <p className="text-label-sm text-on-surface-variant mb-sm">
            จากผู้สมัครที่มีผลแล้ว {total} คน · แสดงสูงสุด 10 อันดับต่อกลุ่ม
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-md">
            <Group
              title="ทักษะที่ต้องมี"
              icon="priority_high"
              items={data.required}
              total={total}
              tone="error"
            />
            <Group
              title="ทักษะที่อยากได้"
              icon="add_circle"
              items={data.preferred}
              total={total}
              tone="tertiary"
            />
          </div>
        </div>
      )}
    </div>
  );
}

function Group({
  title,
  icon,
  items,
  total,
  tone,
}: {
  title: string;
  icon: string;
  items: SkillGapCount[];
  total: number;
  tone: "error" | "tertiary";
}) {
  const head = tone === "error" ? "text-error" : "text-tertiary";
  const bar = tone === "error" ? "bg-error/70" : "bg-tertiary/70";
  const wrap =
    tone === "error"
      ? "bg-error-container/20 border-error/10"
      : "bg-tertiary-container/15 border-tertiary/10";

  return (
    <div className={`p-sm rounded-xl border ${wrap}`}>
      <p className={`flex items-center gap-xs text-label-md font-bold mb-xs ${head}`}>
        <span className="material-symbols-outlined text-[18px]" aria-hidden>
          {icon}
        </span>
        {title}
      </p>

      {items.length === 0 ? (
        <p className="text-label-sm text-on-surface-variant">ไม่มีใครขาดทักษะกลุ่มนี้</p>
      ) : (
        <ul className="space-y-xs">
          {items.map((it) => {
            const pct = Math.round((it.missing_count / total) * 100);
            return (
              <li key={it.skill}>
                <div className="flex items-baseline justify-between gap-xs">
                  <span className="text-label-md text-on-surface min-w-0 break-words">
                    {skillLabel(it.skill)}
                  </span>
                  <span className="flex-none text-label-sm text-on-surface-variant">
                    ขาด <b className="text-on-surface">{it.missing_count}</b> จาก {total} คน
                  </span>
                </div>
                <div
                  className="mt-1 h-2 rounded-full bg-glass/60 border border-outline/15 overflow-hidden"
                  role="img"
                  aria-label={`${skillLabel(it.skill)} ขาด ${it.missing_count} จาก ${total} คน (${pct}%)`}
                >
                  {/* ความกว้างคำนวณจากข้อมูล ไม่ใช่สี */}
                  <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct}%` }} />
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
