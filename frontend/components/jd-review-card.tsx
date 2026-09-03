import { SCOPE } from "@/lib/types";
import type { JDReview } from "@/lib/types";

/**
 * ผลตรวจร่างประกาศก่อนโพสต์ — เป็น "คำแนะนำ" ไม่ใช่ด่านบังคับ
 * HR จะแก้ตามหรือกดสร้างงานเลยก็ได้ (human-in-the-loop เหมือนทุกจุดของระบบ)
 *
 * โทนสีใช้สูตร notice เดิมจาก components/file-upload.tsx —
 * ⚠️ ตัวอักษรต้องเป็น on-surface/on-surface-variant เสมอ ห้ามใช้สีโทน
 * เพราะตระกูล *-fixed ตั้งใจให้เหมือนกันทั้งสองธีม พอวางบนพื้นมืดแล้วอ่านไม่ออก
 */
export default function JDReviewCard({ review }: { review: JDReview }) {
  const scope = SCOPE[review.scope_assessment] ?? SCOPE.balanced;
  const clean =
    review.bias_flags.length === 0 &&
    review.must_have_review.length === 0 &&
    review.missing_info.length === 0;

  return (
    <div className="glass-card rounded-2xl p-md space-y-sm">
      <div className="flex items-center gap-xs flex-wrap">
        <h3 className="text-headline-md text-on-surface flex items-center gap-xs">
          <span className="material-symbols-outlined text-primary">rate_review</span>
          ผลตรวจร่างประกาศ
        </h3>
        <span
          className={`inline-flex items-center gap-1 px-3 py-1 rounded-full text-label-sm font-bold whitespace-nowrap ${scope.chip}`}
        >
          <span className="material-symbols-outlined text-[14px]">{scope.icon}</span>
          {scope.label}
        </span>
      </div>

      {review.scope_comment && (
        <p className="text-on-surface-variant text-label-md leading-snug">
          {review.scope_comment}
        </p>
      )}

      {clean && (
        <div className="p-sm rounded-xl border border-secondary/30 bg-secondary-container/10 flex gap-xs items-start">
          <span
            className="material-symbols-outlined text-secondary text-[20px]"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            task_alt
          </span>
          <p className="text-on-surface text-label-md leading-snug">
            ไม่พบประเด็นที่ต้องแก้ — ประกาศนี้พร้อมโพสต์
          </p>
        </div>
      )}

      {review.bias_flags.length > 0 && (
        <Notice
          tone="tertiary"
          icon="report"
          title={`ถ้อยคำที่อาจกีดกันผู้สมัคร ${review.bias_flags.length} จุด`}
        >
          <ul className="space-y-xs mt-1">
            {review.bias_flags.map((f, i) => (
              <li key={i}>
                <p className="text-on-surface text-label-md leading-snug">
                  <q className="italic">{f.phrase}</q>
                </p>
                <p className="text-on-surface-variant text-label-sm leading-snug">
                  {f.reason} · แนะนำ: {f.suggestion}
                </p>
              </li>
            ))}
          </ul>
        </Notice>
      )}

      {review.must_have_review.length > 0 && (
        <Notice
          tone="tertiary"
          icon="checklist"
          title={`ทักษะที่ระบุว่า "ต้องมี" แต่ควรทบทวน ${review.must_have_review.length} ข้อ`}
        >
          <ul className="space-y-xs mt-1">
            {review.must_have_review.map((m, i) => (
              <li key={i}>
                <p className="text-on-surface text-label-md leading-snug">{m.skill}</p>
                <p className="text-on-surface-variant text-label-sm leading-snug">
                  {m.reason}
                </p>
              </li>
            ))}
          </ul>
        </Notice>
      )}

      {review.missing_info.length > 0 && (
        <Notice tone="primary" icon="info" title="ข้อมูลที่ยังขาด">
          <p className="text-on-surface-variant text-label-sm leading-snug mt-0.5">
            {review.missing_info.join(" · ")}
          </p>
        </Notice>
      )}

      {review.overall_comment && (
        <p className="text-on-surface-variant text-label-md leading-relaxed border-t border-outline-variant/30 pt-sm">
          {review.overall_comment}
        </p>
      )}
    </div>
  );
}

function Notice({
  tone,
  icon,
  title,
  children,
}: {
  tone: "tertiary" | "primary";
  icon: string;
  title: string;
  children?: React.ReactNode;
}) {
  const wrap =
    tone === "tertiary"
      ? "border-tertiary/30 bg-tertiary-container/10"
      : "border-primary/30 bg-primary-container/10";
  const iconTone = tone === "tertiary" ? "text-tertiary" : "text-primary";

  return (
    <div className={`p-sm rounded-xl border flex gap-xs items-start ${wrap}`}>
      <span
        className={`material-symbols-outlined text-[20px] flex-none ${iconTone}`}
        style={{ fontVariationSettings: "'FILL' 1" }}
      >
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-on-surface text-label-md font-semibold leading-snug">
          {title}
        </p>
        {children}
      </div>
    </div>
  );
}
