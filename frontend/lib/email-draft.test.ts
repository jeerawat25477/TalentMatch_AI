import { test } from "node:test";
import assert from "node:assert/strict";
import { appendScheduleLine, fillTemplate, scheduleLine } from "./email-draft";

const VARS = { candidate_name: "สมชาย ใจดี", job_title: "Backend Developer" };

test("แทนชื่อผู้สมัครและตำแหน่ง", () => {
  assert.equal(
    fillTemplate("เรียน {candidate_name} ตำแหน่ง {job_title}", VARS),
    "เรียน สมชาย ใจดี ตำแหน่ง Backend Developer",
  );
});

test("แทนวันนัดและสถานที่เมื่อมีค่า", () => {
  const out = fillTemplate("นัด {interview_datetime} ที่ {interview_location}", {
    ...VARS,
    interview_datetime: "22 ก.ย. 2569 10:00",
    interview_location: "ห้องประชุม 2",
  });
  assert.equal(out, "นัด 22 ก.ย. 2569 10:00 ที่ ห้องประชุม 2");
});

test("ยังไม่มีวันนัด ต้องปล่อยตัวแปรไว้ ไม่แทนด้วยค่าว่าง", () => {
  // แทนด้วยค่าว่างแล้วอีเมลจะกลายเป็น "ขอเชิญสัมภาษณ์วันที่ " ซึ่ง HR กดส่งได้โดยไม่ทันสังเกต
  const out = fillTemplate("ขอเชิญสัมภาษณ์วันที่ {interview_datetime}", VARS);
  assert.equal(out, "ขอเชิญสัมภาษณ์วันที่ {interview_datetime}");
});

test("ค่าว่างเปล่าก็ยังนับว่าไม่มี", () => {
  const out = fillTemplate("ที่ {interview_location}", {
    ...VARS,
    interview_location: "",
  });
  assert.equal(out, "ที่ {interview_location}");
});

test("ตัวแปรที่ไม่รู้จักไม่ถูกลบทิ้ง", () => {
  assert.equal(fillTemplate("สวัสดี {unknown_var}", VARS), "สวัสดี {unknown_var}");
});

test("บรรทัดวันนัด — ไม่มีสถานที่ก็ไม่ขึ้นบรรทัดสถานที่เปล่า", () => {
  assert.equal(scheduleLine("22 ก.ย. 10:00"), "วันเวลาสัมภาษณ์: 22 ก.ย. 10:00");
  assert.equal(
    scheduleLine("22 ก.ย. 10:00", "  ห้อง 2 "),
    "วันเวลาสัมภาษณ์: 22 ก.ย. 10:00\nสถานที่: ห้อง 2",
  );
});

test("กดแทรกวันนัดซ้ำไม่ได้บรรทัดซ้ำ", () => {
  const line = scheduleLine("22 ก.ย. 10:00");
  const once = appendScheduleLine("เรียน คุณสมชาย", line);
  assert.equal(once, "เรียน คุณสมชาย\n\nวันเวลาสัมภาษณ์: 22 ก.ย. 10:00\n");
  assert.equal(appendScheduleLine(once, line), once);
});

test("เนื้อความว่างก็แทรกได้ ไม่มีบรรทัดเปล่านำหน้า", () => {
  assert.equal(appendScheduleLine("", "วันเวลาสัมภาษณ์: x"), "วันเวลาสัมภาษณ์: x\n");
});
