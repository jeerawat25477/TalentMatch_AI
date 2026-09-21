/**
 * ตัวช่วยของขั้นยื่นข้อเสนอ — ฟังก์ชันบริสุทธิ์ล้วน ไม่ import อะไรจากในโปรเจกต์
 * (แยกไฟล์ให้ `npm run test:unit` คอมไพล์เดี่ยว ๆ ได้ เหมือน email-draft.ts)
 */

export type OfferResponse = "pending" | "accepted" | "declined";

export interface OfferLike {
  position: string;
  /** NUMERIC มาเป็น string ผ่าน JSON */
  salary: string | number | null;
  start_date: string | null;
  respond_by: string | null;
  response: OfferResponse;
}

/**
 * วันนี้ตามปฏิทินบนเครื่องของ HR (YYYY-MM-DD)
 *
 * ไม่ใช้ toISOString().slice(0, 10) เพราะนั่นคือวันที่ของ UTC — ในไทยก่อนเจ็ดโมงเช้าจะได้
 * "เมื่อวาน" แล้วข้อเสนอที่ครบกำหนดวันนี้จะยังไม่ขึ้นว่าเลยกำหนด หรือวันเริ่มงานเลื่อนไปหนึ่งวัน
 */
export function localToday(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** บวกวันให้วันที่ YYYY-MM-DD — คำนวณบน UTC ล้วน ผลจึงไม่ขึ้นกับโซนเวลาของเครื่อง */
export function addDaysIso(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + days));
  return t.toISOString().slice(0, 10);
}

/**
 * เลยวันที่ต้องตอบแล้วแต่ยังไม่มีคำตอบ — คำนวณฝั่งหน้าเว็บโดยตั้งใจ
 *
 * backend ไม่รู้ว่าผู้ใช้อยู่โซนเวลาไหน "วันนี้" จึงต้องมาจากเครื่องของ HR · ตรงวันที่ต้องตอบ
 * พอดียังไม่นับว่าเลย (ผู้สมัครยังตอบได้ทั้งวัน) · เทียบสตริง YYYY-MM-DD ได้ตรง ๆ
 */
export function isOfferOverdue(
  offer: Pick<OfferLike, "respond_by" | "response"> | null | undefined,
  today: string,
): boolean {
  if (!offer || offer.response !== "pending" || !offer.respond_by) return false;
  return today > offer.respond_by;
}

/** ช่วงทดลองงานเริ่มต้น (วัน) — ตรงกับค่าเดิมของหน้าต่างรับเข้าเป็นพนักงาน */
export const PROBATION_DAYS = 90;

/**
 * ค่าเริ่มต้นของหน้าต่างรับเข้าเป็นพนักงาน — ถ้ามีข้อเสนอ ใช้ค่าจากข้อเสนอ HR จะได้ไม่ต้อง
 * พิมพ์ตำแหน่ง เงินเดือน วันเริ่มงานซ้ำ · วันครบทดลองงานนับจาก **วันเริ่มงาน** ไม่ใช่วันนี้
 * (เดิมนับจากวันนี้ ซึ่งผิดทันทีที่วันเริ่มงานอยู่ในอนาคต เช่นรอผู้สมัครลาออกจากที่เดิม 30 วัน)
 */
export function hireDefaults(
  offer: OfferLike | null | undefined,
  jobTitle: string,
  today: string,
): { position: string; salary: string; startDate: string; probationEnd: string } {
  const startDate = offer?.start_date || today;
  const salary =
    offer?.salary != null && offer.salary !== "" && Number.isFinite(Number(offer.salary))
      ? String(Number(offer.salary)) // "45000.00" → "45000" ให้ช่องกรอกอ่านง่าย
      : "";
  return {
    position: offer?.position?.trim() || jobTitle,
    salary,
    startDate,
    probationEnd: addDaysIso(startDate, PROBATION_DAYS),
  };
}
