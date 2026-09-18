import {
  barPercent,
  formatPoints,
  oneSidedNote,
  SIDE_EMPTY,
  SIDE_LABEL,
  sideAriaLabel,
  sideLabel,
  type SideKey,
} from "@/lib/score-breakdown";
import type { ScoreBreakdown as Breakdown } from "@/lib/types";

// สีแท่งใช้โทเคนทั่วไป ไม่ใช่สีแบนด์คะแนน (--band-*) ซึ่งสงวนไว้ให้ตัวเลขคะแนนรวมเท่านั้น
// ถ้าแท่งเป็นสีเขียว/เหลือง/แดงตามแบนด์ ตาจะอ่านว่าแต่ละฝั่ง "ผ่าน/ไม่ผ่าน" ซึ่งไม่ใช่ความหมาย
const BAR_COLOR: Record<SideKey, string> = {
  required: "bg-primary",
  preferred: "bg-secondary",
};

/**
 * แท่งแยกองค์ประกอบคะแนน — ตอบว่า "ทักษะที่ตรงแปลงเป็น fit score ยังไง"
 *
 * คู่กับ RadarChart ที่ตอบ "ทักษะไหนตรง/ขาด" เชิงคุณภาพ ส่วนตัวนี้เชิงปริมาณ
 * ⚠️ แสดงผลอย่างเดียว ไม่มีสูตร ตัวเลขทุกตัวมาจาก backend (ดู lib/score-breakdown.ts)
 */
export default function ScoreBreakdown({
  breakdown,
  fitScore,
}: {
  breakdown: Breakdown;
  fitScore: number;
}) {
  if (breakdown.no_criteria) {
    return (
      <section className="glass-card rounded-2xl p-md space-y-xs">
        <Heading />
        <p className="text-label-md text-on-surface-variant">
          ประกาศงานนี้ยังไม่มีเกณฑ์ทักษะให้เทียบ คะแนน {fitScore} จึงเป็นค่ากลางที่รอคนตัดสิน
          ไม่ได้มาจากการเทียบทักษะ
        </p>
      </section>
    );
  }

  const note = oneSidedNote(breakdown);

  return (
    <section className="glass-card rounded-2xl p-md space-y-sm">
      <Heading />

      {(["required", "preferred"] as SideKey[]).map((key) => {
        const side = breakdown[key];
        return (
          <div key={key} className="space-y-1">
            <div className="flex items-baseline justify-between gap-xs flex-wrap">
              <span className="text-label-md font-semibold text-on-surface">
                {SIDE_LABEL[key]}
              </span>
              {side && (
                <span className="text-label-sm text-on-surface-variant tabular-nums">
                  {sideLabel(side)}
                </span>
              )}
            </div>
            {side ? (
              <div
                className="h-2.5 rounded-full bg-surface-container-high overflow-hidden"
                role="img"
                aria-label={sideAriaLabel(key, side)}
              >
                <div
                  className={`h-full rounded-full ${BAR_COLOR[key]}`}
                  style={{ width: `${barPercent(side)}%` }}
                />
              </div>
            ) : (
              // ฝั่งที่ JD ไม่ได้ระบุ: ข้อความแทนแท่ง — แท่งว่างจะดูเหมือนผู้สมัครได้ศูนย์
              // text-on-surface-variant ไม่ใช่ text-outline: outline บนการ์ดกระจกมืดได้แค่ ~4.3:1
              <p className="text-label-sm text-on-surface-variant">{SIDE_EMPTY[key]}</p>
            )}
          </div>
        );
      })}

      {note && <p className="text-label-sm text-on-surface-variant">{note}</p>}

      <div className="flex items-baseline justify-between gap-xs pt-xs border-t border-outline-variant/40">
        <span className="text-label-md text-on-surface-variant">รวม</span>
        <span className="text-label-md font-semibold text-on-surface tabular-nums">
          {formatPoints(breakdown.total)} → {fitScore} คะแนน
        </span>
      </div>

      {!breakdown.matches_stored_score && (
        <div
          role="note"
          className="flex gap-base items-start p-xs rounded-lg border border-tertiary/40 bg-tertiary-container/10"
        >
          <span
            className="material-symbols-outlined text-tertiary text-[16px] flex-none"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            warning
          </span>
          <p className="text-label-sm text-on-surface-variant leading-snug">
            คะแนน {fitScore} ที่บันทึกไว้คำนวณด้วยสูตรเดิม ตัวเลขด้านบนคือสูตรปัจจุบัน
            ซึ่งจะได้ {Math.round(breakdown.total)} ถ้าคำนวณใหม่
          </p>
        </div>
      )}
    </section>
  );
}

function Heading() {
  return (
    <h3 className="text-label-md font-bold text-on-surface flex items-center gap-xs">
      <span className="material-symbols-outlined text-primary text-[20px]">stacked_bar_chart</span>
      ที่มาของคะแนน
    </h3>
  );
}
