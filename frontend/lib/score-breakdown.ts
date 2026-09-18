/**
 * ข้อความของแท่งแยกองค์ประกอบคะแนน — ฟังก์ชันบริสุทธิ์ ไม่แตะ DOM
 *
 * ⚠️ ไฟล์นี้ **ไม่มีสูตรคะแนน** ไม่มีเลข 60/40 ไม่มีการเฉลี่ยน้ำหนัก ตัวเลขทุกตัวมาจาก
 * backend (matcher.py::score_breakdown ซึ่งเป็นสูตรเดียวกับ fit_score) ที่นี่แค่จัดรูปแบบ
 * ถ้าต้องการตัวเลขใหม่ ให้เพิ่มที่ backend ไม่ใช่คำนวณเองที่นี่
 */
import type { ScoreBreakdown, ScoreSide } from "./types";

export type SideKey = "required" | "preferred";

export const SIDE_LABEL: Record<SideKey, string> = {
  required: "ทักษะที่ต้องมี",
  preferred: "ทักษะที่อยากได้",
};

// ข้อความเมื่อ JD ไม่ได้ระบุฝั่งนั้น — ต้องไม่ดูเหมือนผู้สมัครเสียคะแนน (ไม่ใช่ "0 จาก 0")
export const SIDE_EMPTY: Record<SideKey, string> = {
  required: "ตำแหน่งนี้ไม่ได้ระบุทักษะที่ต้องมี",
  preferred: "ตำแหน่งนี้ไม่ได้ระบุทักษะเสริม",
};

/** คะแนนแบบอ่านง่าย: ลงตัวแสดงเป็นจำนวนเต็ม ไม่ลงตัวแสดงทศนิยม 1 ตำแหน่ง */
export function formatPoints(n: number): string {
  const r = Math.round(n * 10) / 10;
  return Number.isInteger(r) ? String(r) : r.toFixed(1);
}

/** ความยาวแท่งเป็นเปอร์เซ็นต์ 0-100 = สัดส่วนข้อที่ตรงของฝั่งนั้น */
export function barPercent(side: ScoreSide): number {
  if (side.total <= 0) return 0;
  return Math.max(0, Math.min(100, (side.matched / side.total) * 100));
}

/** ป้ายของแท่งหนึ่งฝั่ง เช่น "2/3 ข้อ · 40 จาก 60 คะแนน" */
export function sideLabel(side: ScoreSide): string {
  return `${side.matched}/${side.total} ข้อ · ${formatPoints(side.points)} จาก ${formatPoints(side.weight)} คะแนน`;
}

/** ประโยคเต็มสำหรับสกรีนรีดเดอร์ */
export function sideAriaLabel(key: SideKey, side: ScoreSide): string {
  return `${SIDE_LABEL[key]} ตรง ${side.matched} จาก ${side.total} ข้อ ได้ ${formatPoints(
    side.points,
  )} จาก ${formatPoints(side.weight)} คะแนน`;
}

/**
 * หมายเหตุเมื่อ JD ระบุแค่ฝั่งเดียว — อธิบายว่าทำไมฝั่งนั้นคิดเต็ม 100 ไม่ใช่ 60 หรือ 40
 * คืน null ถ้ามีทั้งสองฝั่ง หรือไม่มีเกณฑ์เลย
 */
export function oneSidedNote(b: ScoreBreakdown): string | null {
  if (b.no_criteria) return null;
  const only: SideKey | null =
    b.required && !b.preferred ? "required" : b.preferred && !b.required ? "preferred" : null;
  if (!only) return null;
  const side = b[only] as ScoreSide;
  return `ตำแหน่งนี้ระบุแค่${SIDE_LABEL[only]} จึงคิดเต็ม ${formatPoints(side.weight)} คะแนน`;
}
