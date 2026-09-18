/**
 * เทสข้อความแท่งแยกองค์ประกอบคะแนน — รัน: docker compose exec -T frontend npm run test:unit
 *
 * ตัวเลขใน input ทุกชุดคือค่าที่ backend (matcher.py::score_breakdown) คืนมาจริงสำหรับกรณีนั้น
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  barPercent,
  formatPoints,
  oneSidedNote,
  sideAriaLabel,
  sideLabel,
} from "./score-breakdown";
import type { ScoreBreakdown } from "./types";

const bothSides: ScoreBreakdown = {
  required: { matched: 2, total: 3, weight: 60, points: 40 },
  preferred: { matched: 1, total: 3, weight: 40, points: 40 / 3 },
  total: 40 + 40 / 3,
  no_criteria: false,
  matches_stored_score: true,
};

const requiredOnly: ScoreBreakdown = {
  required: { matched: 1, total: 4, weight: 100, points: 25 },
  preferred: null,
  total: 25,
  no_criteria: false,
  matches_stored_score: true,
};

const noCriteria: ScoreBreakdown = {
  required: null,
  preferred: null,
  total: 50,
  no_criteria: true,
  matches_stored_score: true,
};

test("ทั้งสองฝั่ง: ป้ายบอกทั้งจำนวนข้อและคะแนนจากน้ำหนักที่ได้มา", () => {
  assert.equal(sideLabel(bothSides.required!), "2/3 ข้อ · 40 จาก 60 คะแนน");
  assert.equal(sideLabel(bothSides.preferred!), "1/3 ข้อ · 13.3 จาก 40 คะแนน");
  assert.equal(oneSidedNote(bothSides), null);
});

test("ฝั่งเดียว: คิดเต็ม 100 และมีหมายเหตุอธิบาย", () => {
  assert.equal(sideLabel(requiredOnly.required!), "1/4 ข้อ · 25 จาก 100 คะแนน");
  assert.equal(oneSidedNote(requiredOnly), "ตำแหน่งนี้ระบุแค่ทักษะที่ต้องมี จึงคิดเต็ม 100 คะแนน");
});

test("ไม่มีเกณฑ์เลย: ไม่มีหมายเหตุฝั่งเดียว (หน้าเว็บแสดงข้อความแยก)", () => {
  assert.equal(oneSidedNote(noCriteria), null);
});

test("ความยาวแท่ง = สัดส่วนข้อที่ตรง และไม่หลุดช่วง 0-100", () => {
  assert.equal(barPercent({ matched: 2, total: 4, weight: 60, points: 30 }), 50);
  assert.equal(barPercent({ matched: 0, total: 3, weight: 60, points: 0 }), 0);
  assert.equal(barPercent({ matched: 3, total: 3, weight: 40, points: 40 }), 100);
  assert.equal(barPercent({ matched: 0, total: 0, weight: 0, points: 0 }), 0);
});

test("ทศนิยม: ลงตัวไม่มีจุด ไม่ลงตัวหนึ่งตำแหน่ง", () => {
  assert.equal(formatPoints(40), "40");
  assert.equal(formatPoints(40 / 3), "13.3");
  assert.equal(formatPoints(26.666), "26.7");
});

test("ข้อความสกรีนรีดเดอร์เป็นประโยคเต็ม", () => {
  assert.equal(
    sideAriaLabel("preferred", bothSides.preferred!),
    "ทักษะที่อยากได้ ตรง 1 จาก 3 ข้อ ได้ 13.3 จาก 40 คะแนน",
  );
});

test("ไฟล์แสดงผลต้องไม่มีสูตรหรือน้ำหนัก 60/40 ของตัวเอง", () => {
  // ตัวเลขน้ำหนักต้องมาจาก backend เท่านั้น ถ้ามีคนเผลอฝังสูตรลงมา เทสนี้จะจับได้
  // (เช็คไฟล์ต้นฉบับ .ts ไม่ใช่ไฟล์ที่คอมไพล์แล้วใน /tmp)
  for (const f of ["lib/score-breakdown.ts", "components/score-breakdown.tsx"]) {
    // ตัดคอมเมนต์และสตริงทิ้งก่อน: คลาส Tailwind อย่าง "border-outline-variant/40" คือ
    // ความทึบของสี ไม่ใช่น้ำหนักคะแนน สิ่งที่หาคือเลข 60/40 ที่เป็นตัวเลขในโค้ดจริง ๆ
    const src = readFileSync(f, "utf8")
      .replace(/\/\/.*$|\/\*[\s\S]*?\*\/|\{\/\*[\s\S]*?\*\/\}/gm, "")
      .replace(/"[^"\n]*"|'[^'\n]*'|`[^`]*`/g, '""');
    assert.doesNotMatch(src, /\b(60|40)\b|WEIGHT/, `${f} มีเลข 60/40 หรือน้ำหนักในโค้ด`);
  }
});
