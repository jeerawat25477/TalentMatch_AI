"use client";

import Link from "next/link";
import { useState } from "react";
import { ApiError } from "@/lib/api";

/** error จาก SWR เป็น 404 จริงไหม — ใช้แยก "ไม่มีอยู่" ออกจาก "ยังโหลดไม่เสร็จ" / "backend ล่ม" */
export const isNotFound = (error: unknown) => error instanceof ApiError && error.status === 404;

/**
 * ธง "ข้อมูลหลักของหน้านี้ไม่มีแล้ว" + option ให้ SWR ตัวหลัก — ใช้ธงนี้หยุด poll แทนการตั้ง key = null
 * (key = null ทำให้ SWR ล้าง error → หน้าคิดว่ายังมีอยู่ → ยิงใหม่ → 404 วนกลับไปกลับมา)
 * · 404 ไม่ retry (error อื่นยัง retry ตามปกติ เพราะ backend ล่มมักหายเอง)
 */
export function useGone() {
  const [gone, setGone] = useState(false);
  return {
    gone,
    swr: {
      shouldRetryOnError: (e: Error) => !isNotFound(e),
      onError: (e: Error) => {
        if (isNotFound(e)) setGone(true);
      },
      onSuccess: () => setGone(false),
    },
  };
}

/**
 * หน้ารายละเอียดที่ข้อมูลหลักไม่มีอยู่ (ถูกลบไปแล้ว หรือลิงก์เก่า).
 * ก่อนมีการ์ดนี้ หน้าผู้สมัคร/พนักงานหมุน "กำลังโหลด…" ตลอดไป และหน้าตำแหน่งดูเหมือนตำแหน่งว่าง ๆ
 * เพราะไม่มีใครอ่าน error ของ SWR — backend ตอบ 404 ถูกอยู่แล้ว (2026-10-14)
 */
export default function NotFoundCard({
  title,
  backHref,
  backLabel,
}: {
  title: string;
  backHref: string;
  backLabel: string;
}) {
  return (
    <div className="glass-card rounded-2xl p-lg text-center space-y-sm max-w-lg mx-auto" role="alert">
      <span className="material-symbols-outlined text-[40px] text-outline" aria-hidden>
        search_off
      </span>
      <h1 className="text-headline-md text-on-surface">{title}</h1>
      <p className="text-label-md text-on-surface-variant">
        อาจถูกลบไปแล้ว หรือลิงก์ไม่ถูกต้อง
      </p>
      <Link href={backHref} className="btn-primary inline-flex">
        {backLabel}
      </Link>
    </div>
  );
}
