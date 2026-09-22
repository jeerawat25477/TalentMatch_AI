"use client";

import { ImageIcon } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { SCREENING_PHOTOS_KEY, fetcher, setScreeningPhotos } from "@/lib/api";
import type { ScreeningPhotosSetting } from "@/lib/types";

/**
 * สวิตช์แสดงรูปผู้สมัครบนหน้าคัดกรอง — เก็บใน DB (app_settings) เหมือนสวิตช์รับอีเมล
 *
 * key ของ SWR ตรงกับ useScreeningPhotos() ในการ์ดผู้สมัคร กดแล้วทุกหน้าที่เปิดอยู่ในแท็บนี้
 * จึงเปลี่ยนตามทันที · หน้าทะเบียนพนักงานไม่ดูสวิตช์นี้ (แสดงรูปเสมอ)
 */
export default function ScreeningPhotosCard() {
  const { data, mutate, error } = useSWR<ScreeningPhotosSetting>(
    SCREENING_PHOTOS_KEY,
    fetcher,
  );
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const enabled = data?.enabled ?? false;

  async function toggle() {
    if (!data || busy) return;
    setBusy(true);
    setSaveError(null);
    mutate({ enabled: !enabled }, false); // optimistic เหมือนสวิตช์รับอีเมล
    try {
      mutate(await setScreeningPhotos(!enabled), false);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "บันทึกไม่สำเร็จ");
      mutate();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="glass-card rounded-2xl p-md space-y-sm">
      <div className="flex items-center justify-between gap-sm">
        <div className="min-w-0">
          <div className="flex items-center gap-xs text-on-surface">
            <ImageIcon className="w-5 h-5 text-primary flex-none" />
            <h2 className="text-label-md font-semibold">แสดงรูปผู้สมัครหน้าคัดกรอง</h2>
          </div>
          <p className="text-label-sm text-on-surface-variant leading-snug mt-0.5">
            {enabled ? "เปิดอยู่" : "ปิดอยู่โดยตั้งใจ"} — เห็นรูปก่อนตัดสินอาจทำให้ตัดสินไม่เป็นกลาง
          </p>
        </div>
        <button
          role="switch"
          aria-checked={enabled}
          aria-label="เปิดหรือปิดการแสดงรูปผู้สมัครหน้าคัดกรอง"
          onClick={toggle}
          disabled={busy || !data}
          className={`relative flex-none w-14 h-8 rounded-full transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
            enabled ? "bg-primary" : "bg-outline/40"
          }`}
        >
          <span
            className={`absolute top-1 w-6 h-6 rounded-full bg-surface shadow-md transition-all ${
              enabled ? "left-7" : "left-1"
            }`}
          />
        </button>
      </div>

      {saveError && (
        <p className="text-error text-label-md" role="alert">
          {saveError}
        </p>
      )}
      {error && !data && (
        <p className="text-error text-label-md" role="alert">
          อ่านค่าไม่สำเร็จ — ลองรีเฟรชหน้าอีกครั้ง
        </p>
      )}
    </section>
  );
}
