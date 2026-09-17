/**
 * เทสลิงก์ Google Calendar — รัน: docker compose exec -T frontend npm run test:unit
 *
 * ใช้ node:test ที่มากับ Node ไม่เพิ่ม dependency · สคริปต์คอมไพล์ด้วย tsc ไปไว้ใน /tmp ก่อน
 * เพราะ Node 20 ในคอนเทนเนอร์ยังรันไฟล์ .ts ตรง ๆ ไม่ได้
 */
import assert from "node:assert/strict";
import test from "node:test";
import {
  googleCalendarUrl,
  interviewDetails,
  interviewTitle,
  toGoogleDate,
} from "./calendar-link";

const START = "2026-09-21T14:00:00+07:00"; // บ่ายสองโมงเวลาไทย = 07:00 UTC

function params(url: string): URLSearchParams {
  return new URL(url).searchParams;
}

test("รูปแบบวันที่เป็น YYYYMMDDTHHmmssZ และเป็นเวลา UTC", () => {
  assert.equal(toGoogleDate(new Date(START)), "20260921T070000Z");
});

test("วันที่ไม่ถูกต้องต้องโยน error ไม่ใช่สร้างลิงก์พัง ๆ", () => {
  assert.throws(() => toGoogleDate(new Date("ไม่ใช่วันที่")));
});

test("เวลาจบ = เริ่ม + 1 ชั่วโมงเป็นค่าเริ่มต้น", () => {
  const url = googleCalendarUrl({ title: "t", start: START });
  assert.equal(params(url).get("dates"), "20260921T070000Z/20260921T080000Z");
});

test("ข้ามเที่ยงคืนแล้ววันเปลี่ยนถูก", () => {
  const url = googleCalendarUrl({ title: "t", start: "2026-12-31T23:30:00Z" });
  assert.equal(params(url).get("dates"), "20261231T233000Z/20270101T003000Z");
});

test("ใช้ action=TEMPLATE บนโดเมน calendar.google.com", () => {
  const u = new URL(googleCalendarUrl({ title: "t", start: START }));
  assert.equal(u.origin + u.pathname, "https://calendar.google.com/calendar/render");
  assert.equal(u.searchParams.get("action"), "TEMPLATE");
});

test("ภาษาไทยและอักขระพิเศษถูก encode แล้วถอดกลับได้ตรงทุกตัว", () => {
  const title = interviewTitle("สมชาย ใจดี", "Backend & DevOps #1");
  const location = "ห้อง 3/2 ชั้น 5? a=b&c";
  const url = googleCalendarUrl({ title, start: START, location });
  // ลิงก์ดิบต้องไม่มีอักขระที่ทำให้ query แตก หรือภาษาไทยที่ยังไม่ encode
  const query = url.split("?")[1];
  assert.doesNotMatch(query, /[ ก-๙#?]/);
  assert.equal(query.split("&").length, 4); // action, text, dates, location เท่านั้น
  assert.equal(params(url).get("text"), "สัมภาษณ์: สมชาย ใจดี — Backend & DevOps #1");
  assert.equal(params(url).get("location"), location);
});

test("ช่องว่างถูก encode เป็น %20 ไม่ใช่ +", () => {
  const url = googleCalendarUrl({ title: "a b", start: START });
  assert.match(url, /text=a%20b/);
});

test("ไม่มีสถานที่หรือรายละเอียด = ไม่ใส่พารามิเตอร์นั้น", () => {
  const p = params(googleCalendarUrl({ title: "t", start: START, location: "  ", details: null }));
  assert.equal(p.has("location"), false);
  assert.equal(p.has("details"), false);
});

test("ลิงก์ไม่มีผู้เข้าร่วมและไม่มีอีเมลผู้สมัคร", () => {
  const name = "สมชาย ใจดี";
  const url = googleCalendarUrl({
    title: interviewTitle(name, "Backend Developer"),
    start: START,
    location: "ออนไลน์ Google Meet",
    details: interviewDetails(name, "Backend Developer", "ออนไลน์ Google Meet"),
  });
  const p = params(url);
  assert.equal(p.has("add"), false);
  assert.doesNotMatch(decodeURIComponent(url), /@/);
  assert.deepEqual([...p.keys()], ["action", "text", "dates", "location", "details"]);
});

test("หัวข้อตามรูปแบบ และไม่มีตำแหน่งก็ยังอ่านรู้เรื่อง", () => {
  assert.equal(interviewTitle("สมชาย", "Backend"), "สัมภาษณ์: สมชาย — Backend");
  assert.equal(interviewTitle("สมชาย", null), "สัมภาษณ์: สมชาย");
});
