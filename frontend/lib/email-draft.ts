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
