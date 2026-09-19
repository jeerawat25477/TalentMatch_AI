import type { GapAnalysis } from "@/lib/types";
import { skillLabel } from "@/lib/skill-group";

// รายการทักษะผ่าน/ขาด — ทำหน้าที่เป็น "table view" ของ radar chart ด้วย
// (ระบุตัวตนด้วยข้อความ ไม่พึ่งสีอย่างเดียว)
export default function SkillGap({
  gap,
  evidence,
}: {
  gap: GapAnalysis | null;
  /** หลักฐานจากเรซูเม่ ต่อทักษะที่ตรงเกณฑ์ — ไม่มี/แถวเก่า = ไม่โชว์ส่วนนี้เลย */
  evidence?: Record<string, string> | null;
}) {
  if (!gap) {
    return <p className="text-label-md text-outline">ยังไม่มีผลวิเคราะห์ทักษะ</p>;
  }
  const matched = [...gap.matched_required, ...gap.matched_preferred];
  const missing = [...gap.missing_required, ...gap.missing_preferred];
  // เรียงตามลำดับทักษะที่ตรงเกณฑ์ ไม่ใช่ลำดับคีย์ที่ backend ส่งมา
  const quotes = matched
    .map((s) => [s, evidence?.[s]] as const)
    .filter((pair): pair is readonly [string, string] => Boolean(pair[1]));

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-md">
      <Panel
        icon="bolt"
        title="ทักษะที่ตรงเกณฑ์"
        count={matched.length}
        skills={matched}
        tone="secondary"
        quotes={quotes}
      />
      <Panel
        icon="history_toggle_off"
        title="ทักษะที่ยังขาด"
        count={missing.length}
        skills={missing}
        tone="error"
      />
    </div>
  );
}

function Panel({
  icon,
  title,
  count,
  skills,
  tone,
  quotes = [],
}: {
  icon: string;
  title: string;
  count: number;
  skills: string[];
  tone: "secondary" | "error";
  quotes?: readonly (readonly [string, string])[];
}) {
  const wrap =
    tone === "secondary"
      ? "bg-secondary-container/20 border-secondary/10"
      : "bg-error-container/20 border-error/10";
  const head = tone === "secondary" ? "text-secondary" : "text-error";
  const chip =
    tone === "secondary"
      ? "bg-secondary-fixed text-on-secondary-fixed-variant"
      : "bg-error/10 text-on-error-container";

  return (
    <div className={`p-md rounded-xl border ${wrap}`}>
      <div className={`flex items-center gap-xs mb-xs ${head}`}>
        <span className="material-symbols-outlined text-[20px]">{icon}</span>
        <span className="text-label-md font-bold">
          {title} ({count})
        </span>
      </div>
      {skills.length === 0 ? (
        <p className="text-label-sm text-outline">—</p>
      ) : (
        <div className="flex flex-wrap gap-base">
          {skills.map((s) => (
            <span
              key={s}
              className={`text-[11px] font-semibold px-2.5 py-1 rounded-full ${chip}`}
            >
              {skillLabel(s)}
            </span>
          ))}
        </div>
      )}

      {/* หลักฐานจากเรซูเม่ — ผ่านการตรวจว่ามีข้อความนี้อยู่ในไฟล์จริงแล้วฝั่ง backend
          ทักษะที่หาหลักฐานยืนยันไม่ได้จะไม่อยู่ในลิสต์นี้ (โชว์เป็นชิปด้านบนอย่างเดียว) */}
      {quotes.length > 0 && (
        <div className="mt-sm pt-sm border-t border-outline-variant/30 space-y-xs">
          <p className="text-label-sm text-outline flex items-center gap-xs">
            <span className="material-symbols-outlined text-[16px]">
              format_quote
            </span>
            หลักฐานจากเรซูเม่ ({quotes.length}/{skills.length})
          </p>
          {quotes.map(([skill, quote]) => (
            <div key={skill}>
              <p className="text-label-sm font-semibold text-on-surface">{skillLabel(skill)}</p>
              <blockquote
                className={`border-l-2 pl-sm mt-0.5 text-label-sm italic text-on-surface-variant ${
                  tone === "secondary" ? "border-secondary/40" : "border-error/40"
                }`}
              >
                {quote}
              </blockquote>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
