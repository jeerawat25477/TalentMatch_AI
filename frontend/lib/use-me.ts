"use client";

import useSWR from "swr";
import { fetcher } from "./api";
import type { UserInfo } from "./types";

export const ME_KEY = "/api/v1/auth/me";

/** ผู้ใช้ปัจจุบัน (SWR ตัวเดียวกันทั้งแอป — AppShell เติม cache ไว้ตอนตรวจ token แล้ว) */
export function useMe() {
  return useSWR<UserInfo>(ME_KEY, fetcher, { revalidateOnFocus: false });
}

/**
 * ทำงานของผู้ดูแลได้ไหม (ลบ · ส่งอีเมลจริง · ตั้งค่าระบบ).
 * ยังโหลดไม่เสร็จ = ถือว่าไม่ได้ — ซ่อนไว้ก่อนดีกว่าโชว์ปุ่มที่กดแล้วโดน 403
 * หน้าเว็บซ่อนเพื่อความสะดวกเท่านั้น backend กันจริงด้วย require_admin
 */
export function useIsAdmin(): boolean {
  return useMe().data?.role === "admin";
}

/** ข้อความสั้น ๆ ใต้ปุ่มที่บัญชีทดลองกดไม่ได้ */
export const DEMO_NOTE = "บัญชีทดลองทำรายการนี้ไม่ได้";
