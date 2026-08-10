import { normalizeQuestions } from "@/lib/types";
import type { InterviewPlan } from "@/lib/types";

// คำถามสัมภาษณ์ + "แนวคำตอบที่คาดหวัง" ให้ HR ใช้เป็นเกณฑ์ประเมินสด ๆ ระหว่างสัมภาษณ์
export default function InterviewGuide({
  plan,
}: {
  plan: InterviewPlan | null;
}) {
  const questions = normalizeQuestions(plan);

  if (questions.length === 0) {
    return (
      <p className="text-label-md text-outline">
        ยังไม่มีคำถาม — จะถูกสร้างเมื่อผู้สมัครผ่านเข้าสู่ขั้นสัมภาษณ์
      </p>
    );
  }

  return (
    <ol className="space-y-sm">
      {questions.map((q, i) => (
        <li key={i} className="flex gap-xs">
          <span className="flex-none w-6 h-6 rounded-full bg-primary/10 text-primary text-label-sm flex items-center justify-center mt-0.5">
            {i + 1}
          </span>
          <div className="min-w-0 flex-1 space-y-xs">
            <p className="text-body-md text-on-surface">{q.question}</p>

            {q.expected_answer && (
              <div className="rounded-lg border border-secondary/20 bg-secondary-container/10 p-xs flex gap-xs">
                <span
                  className="material-symbols-outlined text-secondary text-[18px] flex-none"
                  style={{ fontVariationSettings: "'FILL' 1" }}
                  aria-hidden
                >
                  checklist
                </span>
                <div className="min-w-0">
                  <p className="text-label-sm text-secondary font-bold mb-0.5">
                    แนวคำตอบที่คาดหวัง
                  </p>
                  <p className="text-label-md text-on-surface-variant leading-relaxed">
                    {q.expected_answer}
                  </p>
                </div>
              </div>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}
