import { SCOPE } from "@/lib/types";
import type { JDReview, JDScreeningIssue } from "@/lib/types";

/**
 * ผลตรวจประกาศก่อนกดวิเคราะห์ — ตรวจว่า "ใช้คัดกรองเรซูเม่ได้ดีแค่ไหน" ไม่ใช่ "พร้อมโพสต์ไหม"
 * เป็นคำแนะนำ ไม่ใช่ด่านบังคับ HR จะแก้ตามหรือกดวิเคราะห์เลยก็ได้
 *
 * เรียงตามผลต่อคะแนน: วัดไม่ได้ → กว้างเกิน → โครงสร้าง → ต้องมีที่ควรทบทวน
 * เรื่องของการโพสต์ภายนอก (เงินเดือน/สถานที่) เป็นบรรทัดเล็กท้ายการ์ด เพราะไม่มีผลกับการคัดกรอง
 *
 * โทนสีใช้สูตร notice เดิมจาก components/file-upload.tsx —
 * ⚠️ ตัวอักษรต้องเป็น on-surface/on-surface-variant เสมอ ห้ามใช้สีโทน
 * เพราะตระกูล *-fixed ตั้งใจให้เหมือนกันทั้งสองธีม พอวางบนพื้นมืดแล้วอ่านไม่ออก
 */
export default function JDReviewCard({ review }: { review: JDReview }) {
  const scope = SCOPE[review.scope_assessment] ?? SCOPE.balanced;
  const clean =
    review.unmeasurable.length === 0 &&
    review.vague_skills.length === 0 &&
    review.structure_issues.length === 0 &&
    review.must_have_review.length === 0;

  return (
    <div className="glass-card rounded-2xl p-md space-y-sm">
      <div className="flex items-center gap-xs flex-wrap">
        <h3 className="text-headline-md text-on-surface flex items-center gap-xs">
          <span className="material-symbols-outlined text-primary">rate_review</span>
          ผลตรวจประกาศ
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
            ไม่พบประเด็นที่ต้องแก้ — ประกาศนี้พร้อมใช้คัดกรอง
          </p>
        </div>
      )}

      {review.unmeasurable.length > 0 && (
        <Notice
          tone="tertiary"
          icon="visibility_off"
          title={`เกณฑ์ที่ดูจากเรซูเม่ไม่ได้ ${review.unmeasurable.length} ข้อ`}
        >
          <IssueList items={review.unmeasurable} />
        </Notice>
      )}

      {review.vague_skills.length > 0 && (
        <Notice
          tone="tertiary"
          icon="blur_on"
          title={`ทักษะที่กว้างเกินจนจับคู่ไม่ได้ ${review.vague_skills.length} ข้อ`}
        >
          <IssueList items={review.vague_skills} />
        </Notice>
      )}

      {review.structure_issues.length > 0 && (
        <Notice tone="tertiary" icon="format_list_bulleted" title="โครงสร้างที่ระบบอาจอ่านผิด">
          <ul className="space-y-0.5 mt-1 list-disc ps-4">
            {review.structure_issues.map((s, i) => (
              <li key={i} className="text-on-surface-variant text-label-sm leading-snug">
                {s}
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

      {review.overall_comment && (
        <p className="text-on-surface-variant text-label-md leading-relaxed border-t border-outline-variant/30 pt-sm">
          {review.overall_comment}
        </p>
      )}

      <div className="space-y-0.5">
        {review.posting_tips.length > 0 && (
          <p className="text-outline text-label-sm leading-snug">
            ถ้าจะนำไปโพสต์บนเว็บหางาน ควรเพิ่ม: {review.posting_tips.join(" · ")}
          </p>
        )}
        {/* บอกไว้ HR จะได้ไม่เข้าใจว่าเรื่องอคติถูกข้าม — ย้ายไปตรวจตอนกดวิเคราะห์แล้ว */}
        <p className="text-outline text-label-sm leading-snug">
          เรื่องถ้อยคำที่อาจมีอคติ ระบบตรวจตอนกด “วิเคราะห์”
        </p>
      </div>
    </div>
  );
}

function IssueList({ items }: { items: JDScreeningIssue[] }) {
  return (
    <ul className="space-y-xs mt-1">
      {items.map((f, i) => (
        <li key={i}>
          <p className="text-on-surface text-label-md leading-snug">
            <q className="italic">{f.phrase}</q>
          </p>
          <p className="text-on-surface-variant text-label-sm leading-snug">
            แนะนำ: {f.suggestion}
          </p>
        </li>
      ))}
    </ul>
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
