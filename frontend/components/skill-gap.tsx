import type { GapAnalysis } from "@/lib/types";

// รายการทักษะผ่าน/ขาด — ทำหน้าที่เป็น "table view" ของ radar chart ด้วย
// (ระบุตัวตนด้วยข้อความ ไม่พึ่งสีอย่างเดียว)
export default function SkillGap({ gap }: { gap: GapAnalysis | null }) {
  if (!gap) {
    return <p className="text-label-md text-outline">ยังไม่มีผลวิเคราะห์ทักษะ</p>;
  }
  const matched = [...gap.matched_required, ...gap.matched_preferred];
  const missing = [...gap.missing_required, ...gap.missing_preferred];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-md">
      <Panel
        icon="bolt"
        title="ทักษะที่ตรงเกณฑ์"
        count={matched.length}
        skills={matched}
        tone="secondary"
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
}: {
  icon: string;
  title: string;
  count: number;
  skills: string[];
  tone: "secondary" | "error";
}) {
  const wrap =
    tone === "secondary"
      ? "bg-secondary-container/20 border-secondary/10"
      : "bg-error-container/20 border-error/10";
  const head = tone === "secondary" ? "text-secondary" : "text-error";
  const chip =
    tone === "secondary"
      ? "bg-secondary-fixed/60 text-on-secondary-container"
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
              {s}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
