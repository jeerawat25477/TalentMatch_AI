/**
 * ลิงก์ "เพิ่มลง Google Calendar" — ฟังก์ชันบริสุทธิ์ ไม่แตะ DOM ไม่เรียกเครือข่าย
 *
 * ใช้ URL สาธารณะของ Google ที่แค่เปิดหน้าฟอร์มสร้าง event ให้ HR กดบันทึกเอง
 * **ไม่ใช้ Calendar API ไม่มี OAuth ไม่มี token** ระบบไม่เคยสร้าง event แทนใคร
 *
 * ⚠️ **ไม่มีช่องผู้เข้าร่วม (พารามิเตอร์ `add`) โดยตั้งใจ และห้ามเพิ่ม** ถ้าใส่อีเมล
 * ผู้สมัครลงไป Google อาจส่งคำเชิญถึงผู้สมัครเองทันทีที่ HR กดบันทึก โดยที่ HR ยังไม่ได้
 * ยืนยันเนื้อหา ซึ่งขัดกับหลัก "อีเมลถึงผู้สมัครต้องผ่านการกดยืนยันของ HR เสมอ"
 * ของทั้งระบบ · อีเมลผู้สมัครจึงไม่อยู่ใน type ข้างล่างเลย ส่งเข้ามาไม่ได้ตั้งแต่ต้น
 */

export interface CalendarEvent {
  title: string;
  /** Date หรือสตริง ISO ที่มีโซนเวลา (เช่น scheduled_at จาก API) */
  start: Date | string;
  /** ค่าเริ่มต้น 60 นาที — HR แก้เวลาจบเองในหน้า Google ได้ถ้าไม่ตรง */
  durationMinutes?: number;
  location?: string | null;
  details?: string | null;
}

const BASE = "https://calendar.google.com/calendar/render";

/** แปลงเป็นรูปแบบที่ Google ต้องการ `YYYYMMDDTHHmmssZ` (เวลา UTC เสมอ) */
export function toGoogleDate(d: Date): string {
  if (Number.isNaN(d.getTime())) throw new Error("วันเวลาไม่ถูกต้อง");
  // toISOString คืน UTC อยู่แล้ว เช่น 2026-09-21T07:00:00.000Z → 20260921T070000Z
  return d.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
}

export function googleCalendarUrl(ev: CalendarEvent): string {
  const start = typeof ev.start === "string" ? new Date(ev.start) : ev.start;
  const end = new Date(start.getTime() + (ev.durationMinutes ?? 60) * 60_000);

  const params: [string, string][] = [
    ["action", "TEMPLATE"],
    ["text", ev.title],
    ["dates", `${toGoogleDate(start)}/${toGoogleDate(end)}`],
  ];
  if (ev.location?.trim()) params.push(["location", ev.location.trim()]);
  if (ev.details?.trim()) params.push(["details", ev.details.trim()]);

  // encode ทุกค่าเอง ไม่พึ่ง URLSearchParams: มันเข้ารหัสช่องว่างเป็น "+" ซึ่งบางที่
  // ของ Google แสดงเป็นเครื่องหมายบวกตรง ๆ ในหัวข้อ event
  const query = params
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join("&");
  return `${BASE}?${query}`;
}

/** หัวข้อ event รูปแบบเดียวกันทุกที่ที่มีปุ่มนี้ */
export function interviewTitle(candidateName: string, jobTitle: string | null | undefined): string {
  return jobTitle ? `สัมภาษณ์: ${candidateName} — ${jobTitle}` : `สัมภาษณ์: ${candidateName}`;
}

/** รายละเอียด event — ชื่อ ตำแหน่ง และสถานที่เท่านั้น ไม่มีข้อมูลติดต่อผู้สมัคร */
export function interviewDetails(
  candidateName: string,
  jobTitle: string | null | undefined,
  location: string | null | undefined,
): string {
  return [
    `ผู้สมัคร: ${candidateName}`,
    jobTitle ? `ตำแหน่ง: ${jobTitle}` : null,
    location?.trim() ? `สถานที่: ${location.trim()}` : null,
  ]
    .filter(Boolean)
    .join("\n");
}
