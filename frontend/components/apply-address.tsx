"use client";

import { useState } from "react";
import useSWR from "swr";
import { getEmailIntake } from "@/lib/api";
import { applyAddress } from "@/lib/types";
import type { EmailIntakeSettings } from "@/lib/types";

/**
 * ที่อยู่ที่ผู้สมัครส่งเรซูเม่มาได้โดยตรงสำหรับตำแหน่งนี้ พร้อมปุ่มคัดลอก
 *
 * โชว์เมื่อครบสามข้อเท่านั้น:
 *   1. ปากทางรับอีเมลเปิดอยู่ — ปิดอยู่แล้วโชว์ไว้จะชวนให้เข้าใจผิดว่าใช้ได้
 *   2. ตั้ง IMAP_USER แล้ว (backend คืน template มาให้)
 *   3. ตำแหน่งงานยังเปิดรับ — worker ปฏิเสธงานที่ปิดรับแล้ว (บันทึกเป็น job_closed)
 *      ถ้ายังโชว์ที่อยู่ไว้ HR จะเอาไปประกาศต่อแล้วใบสมัครหายเงียบ
 *      (หน้านี้ซ่อนปุ่มอัปโหลดเมื่องานปิดอยู่แล้วด้วยเหตุผลเดียวกัน)
 *
 * ใช้คีย์ SWR เดียวกับการ์ดในหน้าตั้งค่า — SWR รวม request ให้เอง ไม่ยิงซ้ำ
 */
export default function ApplyAddress({
  jobId,
  jobOpen,
}: {
  jobId: string;
  jobOpen: boolean;
}) {
  const { data } = useSWR<EmailIntakeSettings>("email-intake", getEmailIntake);
  const [copied, setCopied] = useState(false);

  const address = applyAddress(data?.apply_address_template, jobId);
  if (!data?.enabled || !address || !jobOpen) return null;

  async function copy() {
    if (!address) return;
    try {
      // clipboard API ต้องการ secure context — localhost ผ่าน แต่ http บนโดเมนจริงไม่ผ่าน
      await navigator.clipboard.writeText(address);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // คัดลอกอัตโนมัติไม่ได้ก็ยังต้องคัดลอกเองได้ — เลือกข้อความให้เลย
      const el = document.getElementById(`apply-addr-${jobId}`);
      if (el) {
        const range = document.createRange();
        range.selectNodeContents(el);
        const sel = window.getSelection();
        sel?.removeAllRanges();
        sel?.addRange(range);
      }
    }
  }

  return (
    <div className="glass-card rounded-2xl p-md flex items-center gap-sm flex-wrap">
      <span
        className="material-symbols-outlined text-primary text-[22px] flex-none"
        style={{ fontVariationSettings: "'FILL' 1" }}
      >
        forward_to_inbox
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-label-md font-semibold text-on-surface">
          หรือให้ผู้สมัครส่งเรซูเม่มาที่อยู่นี้ได้เลย
        </p>
        <p
          id={`apply-addr-${jobId}`}
          className="text-label-md text-on-surface-variant font-mono break-all mt-0.5"
        >
          {address}
        </p>
      </div>
      <button
        onClick={copy}
        className="btn-secondary-glass flex-none"
        aria-label="คัดลอกที่อยู่อีเมลรับสมัครของตำแหน่งนี้"
      >
        <span className="material-symbols-outlined text-[18px]">
          {copied ? "check" : "content_copy"}
        </span>
        {copied ? "คัดลอกแล้ว" : "คัดลอก"}
      </button>
    </div>
  );
}
