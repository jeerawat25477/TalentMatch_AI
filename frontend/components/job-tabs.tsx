"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * สลับมุมมองของตำแหน่งงานหนึ่ง ระหว่างรายชื่อผู้สมัครกับกระดานติดตาม
 *
 * ⚠️ **กระดานไม่ได้มาแทนหน้ารายชื่อ** — กระดานแสดงเฉพาะคนที่มีการตัดสินเกิดขึ้นแล้ว
 * ส่วนคนที่รอ HR ตัดสิน กำลังวิเคราะห์ ค้าง หรือไม่ผ่านคัดกรอง อยู่ในหน้ารายชื่อเท่านั้น
 * สองหน้านี้จึงต้องอยู่คู่กันเสมอ
 *
 * ใช้ <Link> ไม่ใช่ state เพราะเป็นคนละหน้า: URL ต้องแชร์ได้และปุ่ม back ต้องทำงาน
 */
export default function JobTabs({ jobId }: { jobId: string }) {
  const pathname = usePathname();
  const onBoard = pathname.endsWith("/board");

  const tabs = [
    { href: `/jobs/${jobId}`, label: "รายชื่อผู้สมัคร", icon: "list", active: !onBoard },
    {
      href: `/jobs/${jobId}/board`,
      label: "กระดานติดตาม",
      icon: "view_kanban",
      active: onBoard,
    },
  ];

  return (
    <div className="flex gap-base bg-glass/50 border border-outline/30 backdrop-blur-md p-1 rounded-xl w-fit">
      {tabs.map((t) => (
        <Link
          key={t.href}
          href={t.href}
          aria-current={t.active ? "page" : undefined}
          className={`px-sm py-1.5 rounded-lg text-label-md font-semibold transition-colors inline-flex items-center gap-base ${
            t.active
              ? "bg-primary text-on-primary"
              : "text-on-surface-variant hover:bg-glass/40"
          }`}
        >
          <span className="material-symbols-outlined text-[18px]">{t.icon}</span>
          {t.label}
        </Link>
      ))}
    </div>
  );
}
