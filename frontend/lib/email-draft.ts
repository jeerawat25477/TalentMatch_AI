/**
 * ตัวช่วยร่างอีเมล — ฟังก์ชันบริสุทธิ์ล้วน ไม่ import อะไรจากในโปรเจกต์
 *
 * แยกออกจาก types.ts เพื่อให้ `npm run test:unit` คอมไพล์ไฟล์นี้เดี่ยว ๆ ได้
 * (types.ts ถูก import ทั้งแอป การลากมันเข้าเทสคือลาก React ตามมาด้วย)
 * types.ts re-export ให้ โค้ดเดิมที่ import จาก "@/lib/types" จึงไม่ต้องแก้
 */

/** ตัวแปรที่แทนค่าได้ในเทมเพลต — เติมให้ตอน "เลือก" เทมเพลตเท่านั้น */
export const TEMPLATE_VARS = [
  "{candidate_name}",
  "{job_title}",
  "{interview_datetime}",
  "{interview_location}",
] as const;

export interface TemplateVars {
  candidate_name: string;
  job_title: string;
  /** วันเวลานัดจัดรูปแล้ว — ไม่มีวันนัด = ไม่ต้องส่งมา */
  interview_datetime?: string | null;
  interview_location?: string | null;
}

/**
 * แทนค่าตัวแปรในเทมเพลต
 *
 * ตัวที่ไม่รู้จัก **และตัวที่รู้จักแต่ยังไม่มีค่า** ปล่อยไว้ตามเดิม ไม่ลบทิ้งเงียบ ๆ —
 * ถ้ายังไม่ได้นัดแล้วแทน {interview_datetime} ด้วยค่าว่าง อีเมลจะกลายเป็น
 * "ขอเชิญสัมภาษณ์วันที่ " ซึ่ง HR อาจกดส่งโดยไม่ทันสังเกต · เห็นวงเล็บปีกกาค้างอยู่
 * คือสัญญาณที่มองข้ามยากกว่า
 */
export function fillTemplate(text: string, vars: TemplateVars): string {
  let out = text
    .replaceAll("{candidate_name}", vars.candidate_name)
    .replaceAll("{job_title}", vars.job_title);
  if (vars.interview_datetime) {
    out = out.replaceAll("{interview_datetime}", vars.interview_datetime);
  }
  if (vars.interview_location) {
    out = out.replaceAll("{interview_location}", vars.interview_location);
  }
  return out;
}

/** บรรทัดวันนัดสำหรับแทรกลงเนื้อความ — สถานที่ไม่บังคับ (สัมภาษณ์ออนไลน์ก็มี) */
export function scheduleLine(datetime: string, location?: string | null): string {
  const place = location?.trim();
  return place
    ? `วันเวลาสัมภาษณ์: ${datetime}\nสถานที่: ${place}`
    : `วันเวลาสัมภาษณ์: ${datetime}`;
}

/**
 * แทรกบรรทัดวันนัดต่อท้ายเนื้อความ — กดซ้ำแล้วไม่ควรได้สองบรรทัดเหมือนกัน
 * (HR กดปุ่มซ้ำเพราะไม่แน่ใจว่ากดไปแล้วหรือยัง เป็นเรื่องปกติ)
 */
export function appendScheduleLine(body: string, line: string): string {
  if (body.includes(line)) return body;
  const base = body.replace(/\s+$/, "");
  return base ? `${base}\n\n${line}\n` : `${line}\n`;
}

// ---------- โหมดของการ์ดอีเมล: เชิญ / ปฏิเสธ ----------

export type EmailKind = "invitation" | "rejection";

/**
 * การ์ดอีเมลควรอยู่โหมดไหน
 *
 * ร่างของ AI ถูกสร้างครั้งเดียวตอนกราฟรัน คนที่ผ่านคัดกรองได้ร่างเชิญแล้วจบแค่นั้น
 * พอสัมภาษณ์ไม่ผ่าน การ์ดยังเป็นโหมดเชิญ ตัวเลือกเทมเพลต (ซึ่งกรองตามโหมด) จึงไม่แสดง
 * เทมเพลตปฏิเสธเลย · กติกา:
 * - ผลสัมภาษณ์ "ไม่ผ่าน" หรือขั้น "ไม่ไปต่อ" → ปฏิเสธ
 * - **ยกเว้นผู้สมัครเป็นฝ่ายปฏิเสธข้อเสนอเอง** — ส่งอีเมล "เรายังไม่สามารถดำเนินการต่อกับ
 *   ใบสมัครของท่านได้" ให้คนที่เพิ่งปฏิเสธเราไปคือข้อความที่ผิดทั้งฉบับ
 * - "สำรอง" ยังไม่สลับ — ยังไม่มีใครตัดสินว่าไม่รับ
 * - นอกนั้นตามชนิดร่างของ AI · ไม่มีร่างของ AI ก็อนุมานจากคำตัดสินของ HR
 */
export function emailMode(args: {
  interviewResult: "pass" | "fail" | "standby" | null | undefined;
  boardStage: string | null | undefined;
  aiDraftKind: EmailKind | null | undefined;
  hrDecision: string | null | undefined;
  offerResponse?: "pending" | "accepted" | "declined" | null;
}): EmailKind {
  const candidateDeclinedOffer = args.offerResponse === "declined";
  if (
    !candidateDeclinedOffer &&
    (args.interviewResult === "fail" || args.boardStage === "declined")
  ) {
    return "rejection";
  }
  if (args.aiDraftKind) return args.aiDraftKind;
  return args.hrDecision === "rejected" ? "rejection" : "invitation";
}

/**
 * ร่างปฏิเสธตั้งต้นในตัว — ใช้ได้แม้ HR ยังไม่เคยบันทึกเทมเพลตปฏิเสธ
 *
 * - ไม่ระบุเหตุผล ตามธรรมเนียม HR (เหตุผลเฉพาะในอีเมลปฏิเสธเป็นช่องให้โต้แย้ง)
 * - **ไม่มีประโยค "เราจะเก็บข้อมูลของท่านไว้"** ที่อีเมลปฏิเสธชอบใส่ เพราะเท่ากับสัญญาว่า
 *   จะเก็บข้อมูลส่วนบุคคลไว้ ซึ่งเกี่ยวกับ PDPA ถ้าบริษัทมีนโยบายนี้ HR ใส่เองในเทมเพลตได้
 * - ใช้เฉพาะ {candidate_name} / {job_title} ซึ่งมีค่าเสมอ — ไม่มีตัวแปรวันนัดให้ค้าง
 */
export const DEFAULT_REJECTION = {
  subject: "ผลการพิจารณาใบสมัครตำแหน่ง {job_title}",
  body: [
    "เรียน คุณ{candidate_name}",
    "",
    "ขอขอบคุณที่สละเวลามาร่วมสัมภาษณ์ในตำแหน่ง {job_title} กับเรา",
    "",
    "หลังจากพิจารณาอย่างรอบคอบแล้ว เราเสียใจที่ต้องแจ้งว่าในครั้งนี้เรายังไม่สามารถ" +
      "ดำเนินการต่อกับใบสมัครของท่านได้",
    "",
    "ขอขอบคุณที่ให้ความสนใจร่วมงานกับเรา และขอให้ท่านประสบความสำเร็จในเส้นทางการทำงาน",
    "",
    "ขอแสดงความนับถือ",
    "ฝ่ายทรัพยากรบุคคล",
  ].join("\n"),
} as const;
