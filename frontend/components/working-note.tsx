import { QUEUE_STATE } from "@/lib/types";
import type { QueueStatus } from "@/lib/types";

/**
 * "ระบบกำลังทำอยู่" แทนข้อความว่างเปล่า — ใช้ในช่องที่ผลลัพธ์จะมาทีหลัง
 *
 * หลัง HR กดผ่านคัดกรอง กราฟต้องรันต่ออีกสองโหนด (คำถามสัมภาษณ์ + ร่างอีเมล) ซึ่งกิน
 * เวลาหลายวินาที ระหว่างนั้นการ์ดทั้งสองใบเขียนว่า "ยังไม่มี…" เฉย ๆ แยกไม่ออกเลยว่า
 * กำลังทำอยู่ ล้มไปแล้ว หรือไม่มีวันเกิดขึ้น · หน้า deep dive poll ทุก 4 วินาทีอยู่แล้ว
 * ผลจึงโผล่มาเอง ขาดแค่บอกให้รู้ว่ากำลังรออะไร
 *
 * อ่านจาก `queue_status` ตัวเดียวกับที่หน้ารายชื่อใช้ ไม่ได้เดาจากเวลาหรือสถานะอื่น —
 * "เลื่อนเพราะโควตาเต็ม" จึงไม่ถูกแสดงเป็นไอคอนหมุนทั้งที่ยังไม่มีอะไรเริ่มทำ (ดู CLAUDE.md
 * เรื่อง deferred_quota เป็นการพัก ไม่ใช่ความล้มเหลว)
 */
export default function WorkingNote({
  status,
  what,
}: {
  status: QueueStatus;
  /** สิ่งที่รออยู่ เช่น "คำถามสัมภาษณ์" — เติมท้ายประโยคให้อ่านเป็นภาษาคน */
  what: string;
}) {
  const waiting = status !== "deferred_quota";
  const text =
    status === "running"
      ? `กำลังสร้าง${what}…`
      : status === "queued"
        ? `รอคิว — ระบบจะสร้าง${what}ให้อัตโนมัติ`
        : `โควตา AI วันนี้เต็ม — ระบบจะสร้าง${what}ให้ในวันถัดไป ไม่ต้องกดอะไรเพิ่ม`;

  return (
    <div
      role="status"
      className={`flex items-start gap-xs p-sm rounded-xl ${QUEUE_STATE[status].chip}`}
    >
      <span
        aria-hidden
        className={`material-symbols-outlined text-[18px] flex-none ${
          status === "running" ? "animate-spin" : ""
        }`}
      >
        {QUEUE_STATE[status].icon}
      </span>
      <div className="min-w-0">
        <p className="text-label-md font-semibold">{text}</p>
        {waiting && (
          <p className="text-label-sm opacity-80">
            หน้านี้อัปเดตเองทุก 4 วินาที ไม่ต้องรีเฟรช
          </p>
        )}
      </div>
    </div>
  );
}
