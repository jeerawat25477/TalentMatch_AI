import { test } from "node:test";
import assert from "node:assert/strict";
import { addDaysIso, hireDefaults, isOfferOverdue, localToday } from "./offer";

const OFFER = {
  position: "AI Engineer",
  salary: "45000.00",
  start_date: "2026-11-01",
  respond_by: "2026-10-01",
  response: "pending" as const,
};

test("วันนี้ใช้ปฏิทินบนเครื่อง ไม่ใช่วันที่ของ UTC", () => {
  // หกโมงเช้าเวลาเครื่อง — ถ้าใช้ toISOString บนเครื่องโซน +07 จะได้วันก่อนหน้า
  assert.equal(localToday(new Date(2026, 8, 21, 6, 0)), "2026-09-21");
  assert.equal(localToday(new Date(2026, 0, 5, 23, 59)), "2026-01-05");
});

test("บวกวันข้ามเดือนและข้ามปีได้", () => {
  assert.equal(addDaysIso("2026-09-25", 7), "2026-10-02");
  assert.equal(addDaysIso("2026-12-30", 90), "2027-03-30");
});

test("ตรงวันที่ต้องตอบพอดียังไม่เลยกำหนด", () => {
  assert.equal(isOfferOverdue(OFFER, "2026-10-01"), false);
});

test("เลยวันที่ต้องตอบแล้วยังไม่มีคำตอบ = เลยกำหนด", () => {
  assert.equal(isOfferOverdue(OFFER, "2026-10-02"), true);
});

test("ตอบแล้วไม่นับว่าเลยกำหนด ไม่ว่าจะตอบรับหรือปฏิเสธ", () => {
  assert.equal(isOfferOverdue({ ...OFFER, response: "accepted" }, "2026-12-01"), false);
  assert.equal(isOfferOverdue({ ...OFFER, response: "declined" }, "2026-12-01"), false);
});

test("ไม่ได้กำหนดวันที่ต้องตอบ หรือไม่มีข้อเสนอ ไม่นับว่าเลยกำหนด", () => {
  assert.equal(isOfferOverdue({ ...OFFER, respond_by: null }, "2027-01-01"), false);
  assert.equal(isOfferOverdue(null, "2027-01-01"), false);
});

test("มีข้อเสนอ → หน้าต่างรับเข้าใช้ค่าจากข้อเสนอ และนับทดลองงานจากวันเริ่มงาน", () => {
  assert.deepEqual(hireDefaults(OFFER, "ชื่อตำแหน่งงาน", "2026-09-21"), {
    position: "AI Engineer",
    salary: "45000",
    startDate: "2026-11-01",
    probationEnd: "2027-01-30",
  });
});

test("ไม่มีข้อเสนอ → ตำแหน่งจากชื่อตำแหน่งงาน เริ่มงานวันนี้ เงินเดือนว่าง", () => {
  assert.deepEqual(hireDefaults(null, "Backend Developer", "2026-09-21"), {
    position: "Backend Developer",
    salary: "",
    startDate: "2026-09-21",
    probationEnd: "2026-12-20",
  });
});

test("ข้อเสนอที่ไม่ได้กรอกเงินเดือนหรือวันเริ่มงาน ใช้ค่าตั้งต้นแทน", () => {
  const d = hireDefaults(
    { ...OFFER, salary: null, start_date: null },
    "Backend Developer",
    "2026-09-21",
  );
  assert.equal(d.salary, "");
  assert.equal(d.startDate, "2026-09-21");
});
