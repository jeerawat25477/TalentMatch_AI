import { STAGE_LABEL } from "@/components/board-card";
import { INTERVIEW_RESULT } from "@/lib/types";
import type { CandidateDetail } from "@/lib/types";

/**
 * ไทม์ไลน์ของผู้สมัครหนึ่งคน — อ่านอย่างเดียว ประกอบจากเวลาที่ backend มีอยู่แล้ว
 *
 * **แสดงเฉพาะเหตุการณ์ที่เกิดจริง** จุดไหนไม่มีเวลาก็ไม่มีจุดนั้น ไม่ใช่โชว์จุดว่างไว้
 * ให้เดา — ผู้สมัครที่ถูกปฏิเสธไปแล้วไม่มีทั้งขั้นบนกระดาน ผลสัมภาษณ์ และวันรับเข้า
 * ซึ่งเป็นคนส่วนใหญ่ในระบบ ไทม์ไลน์ของเขาจึงมีแค่ 3-4 จุดและต้องดูปกติ ไม่ใช่ดูพัง
 *
 * แนวตั้ง ไม่ใช่แนวนอน: จำนวนจุดไม่คงที่ (3 ถึง 8) และข้อความกำกับเป็นภาษาไทยยาว ๆ
 * แนวนอนจะบีบจนอ่านไม่ออกบนมือถือ ส่วนแนวตั้งยาวขึ้นได้เรื่อย ๆ โดยไม่ต้องเลื่อนข้าง
 */
type Event = {
  /** เวลาที่ใช้เรียงลำดับ — จุดที่เป็น null ถูกกรองทิ้งก่อนถึงตรงนี้แล้ว */
  at: Date;
  icon: string;
  label: string;
  detail?: string | null;
  /** เวลาที่ยังมาไม่ถึง (วันนัดในอนาคต) — จางลงและบอกว่ายังไม่เกิด */
  upcoming?: boolean;
  /** แสดงวันอย่างเดียว ไม่มีเวลา (interview_outcome.interviewed_at เก็บเป็น date) */
  dateOnly?: boolean;
};

function fmt(d: Date, dateOnly: boolean): string {
  return d.toLocaleString("th-TH", {
    dateStyle: "medium",
    ...(dateOnly ? {} : { timeStyle: "short" }),
  });
}

/** สร้างรายการเหตุการณ์จากข้อมูลที่มี — แยกออกมาให้อ่านง่ายและเรียงที่เดียว */
function buildEvents(c: CandidateDetail): Event[] {
  const events: Event[] = [];
  const push = (
    iso: string | null | undefined,
    icon: string,
    label: string,
    detail?: string | null,
    opts?: { dateOnly?: boolean },
  ) => {
    if (!iso) return;
    // date ล้วน (YYYY-MM-DD) ต้องต่อเวลาเอง ไม่งั้นบางเบราว์เซอร์ตีเป็น UTC แล้ววัน
    // เลื่อนไปหนึ่งวันสำหรับคนที่อยู่โซน +07
    const at = new Date(opts?.dateOnly ? `${iso}T00:00:00` : iso);
    if (Number.isNaN(at.getTime())) return;
    events.push({ at, icon, label, detail, dateOnly: opts?.dateOnly });
  };

  push(c.created_at, "upload_file", "รับเรซูเม่เข้าระบบ");
  push(
    c.evaluated_at,
    "smart_toy",
    "AI วิเคราะห์เสร็จ",
    c.fit_score != null ? `คะแนน ${c.fit_score}` : null,
  );
  push(
    c.hr_decided_at,
    c.hr_decision === "rejected" ? "cancel" : "how_to_reg",
    c.hr_decision === "rejected"
      ? "HR ตัดสินว่าไม่ผ่าน"
      : c.hr_decision === "approved"
        ? "HR อนุมัติให้ไปต่อ"
        : "HR บันทึกคำตัดสิน",
    c.hr_notes,
  );
  push(
    c.email_sent_at,
    "mail",
    c.email_send_count > 1 ? `ส่งอีเมลแล้ว ${c.email_send_count} ครั้ง` : "ส่งอีเมลแล้ว",
    c.email_sent_to,
  );
  // ขั้นล่าสุดบนกระดาน — เก็บได้แถวเดียวต่อคน (hiring_stage.candidate_id เป็น PK)
  // จึงเป็น "ขั้นล่าสุด" ไม่ใช่ประวัติทุกครั้งที่ย้าย ข้อความต้องไม่ทำให้เข้าใจผิด
  if (c.board_stage && c.board_stage !== "hired") {
    push(c.stage_moved_at, "flag", `ย้ายไปขั้น "${STAGE_LABEL[c.board_stage]}"`);
  }
  push(
    c.interview_outcome?.interviewed_at,
    "record_voice_over",
    "สัมภาษณ์",
    c.interview_outcome ? `ผล: ${INTERVIEW_RESULT[c.interview_outcome.result].label}` : null,
    { dateOnly: true },
  );
  push(c.hired_at, "badge", "รับเข้าเป็นพนักงาน");

  events.sort((a, b) => a.at.getTime() - b.at.getTime());

  // วันนัดสัมภาษณ์อยู่ท้ายสุดเสมอเมื่อยังไม่ถึง — มันคือสิ่งที่จะเกิด ไม่ใช่สิ่งที่เกิดแล้ว
  // (ถ้าผ่านมาแล้วก็ยังอยู่ท้าย เพราะเป็นเวลาล่าสุดอยู่ดี เว้นแต่มีผลสัมภาษณ์ทีหลัง)
  if (c.scheduled_at) {
    const at = new Date(c.scheduled_at);
    if (!Number.isNaN(at.getTime())) {
      const upcoming = at.getTime() > Date.now();
      const e: Event = {
        at,
        icon: "event",
        label: upcoming ? "นัดสัมภาษณ์ (ยังไม่ถึง)" : "ถึงเวลานัดสัมภาษณ์",
        detail: c.location,
        upcoming,
      };
      const i = events.findIndex((x) => x.at.getTime() > at.getTime());
      if (i === -1) events.push(e);
      else events.splice(i, 0, e);
    }
  }
  return events;
}

export default function CandidateTimeline({ candidate }: { candidate: CandidateDetail }) {
  const events = buildEvents(candidate);

  return (
    <section className="glass-card rounded-2xl p-md">
      <h3 className="text-headline-md text-on-surface flex items-center gap-xs mb-xs">
        <span className="material-symbols-outlined text-primary">timeline</span>
        ไทม์ไลน์
      </h3>
      <p className="text-label-sm text-on-surface-variant mb-sm">
        เรียงตามเวลา — แสดงเฉพาะสิ่งที่เกิดขึ้นแล้ว
      </p>

      {events.length === 0 ? (
        <p className="text-label-md text-outline">ยังไม่มีเหตุการณ์ให้แสดง</p>
      ) : (
        <ol className="space-y-sm">
          {events.map((e, i) => (
            <li key={`${e.label}-${e.at.getTime()}`} className="flex gap-sm">
              {/* เส้นกับจุด: เส้นต่อจากจุดลงไปหาอันถัดไป จุดสุดท้ายไม่มีเส้น */}
              <div className="flex flex-col items-center flex-none">
                <span
                  className={`material-symbols-outlined text-[18px] w-8 h-8 rounded-full flex items-center justify-center ${
                    e.upcoming
                      ? "bg-glass/60 border border-outline/40 text-on-surface-variant"
                      : "bg-primary/10 text-primary"
                  }`}
                >
                  {e.icon}
                </span>
                {i < events.length - 1 && (
                  <span className="flex-1 w-px my-0.5 bg-outline/30" aria-hidden />
                )}
              </div>
              <div className={`flex-1 min-w-0 pb-xs ${e.upcoming ? "opacity-70" : ""}`}>
                <p className="text-label-md font-semibold text-on-surface">{e.label}</p>
                <p className="text-label-sm text-on-surface-variant">
                  {fmt(e.at, Boolean(e.dateOnly))}
                </p>
                {e.detail && (
                  <p className="text-label-sm text-on-surface-variant break-words">
                    {e.detail}
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
