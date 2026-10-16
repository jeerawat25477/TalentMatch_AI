"use client";

import { Mail } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { getEmailIntake, setEmailIntake } from "@/lib/api";
import type { EmailIntakeSettings } from "@/lib/types";
import { useIsAdmin } from "@/lib/use-me";

/**
 * การ์ดเปิด/ปิดปากทางรับใบสมัครทางอีเมล
 *
 * สวิตช์เก็บใน DB ฝั่ง backend (ตาราง app_settings) ไม่ใช่ state ในหน้านี้ —
 * รีเฟรชแล้วค่าต้องคงอยู่ และ worker อ่านค่าเดียวกันทุกรอบ tick
 *
 * ⚠️ credential ของ IMAP ไม่มีช่องให้กรอกที่นี่โดยตั้งใจ: มันอ่านจาก env ฝั่ง backend
 * เท่านั้น หน้านี้ทำได้แค่เปิด/ปิด (ดู CLAUDE.md หัวข้อ Secrets)
 */
export default function EmailIntakeCard() {
  const { data, mutate, error } = useSWR<EmailIntakeSettings>(
    "email-intake",
    getEmailIntake,
    { refreshInterval: 15000 }, // สถานะ/ตัวนับขยับเองเมื่อ worker ทำงาน
  );
  const [busy, setBusy] = useState(false);
  const isAdmin = useIsAdmin(); // ตั้งค่าระบบ = งานผู้ดูแล บัญชีทดลองดูได้อย่างเดียว
  const [saveError, setSaveError] = useState<string | null>(null);

  const enabled = data?.enabled ?? false;
  const configured = data?.imap_configured ?? false;

  async function toggle() {
    if (!data || busy || !configured) return;
    setBusy(true);
    setSaveError(null);
    // optimistic: สวิตช์ที่หน่วงจะชวนให้ HR กดซ้ำ — แสดงผลก่อนแล้วค่อยยืนยันกับ server
    mutate({ ...data, enabled: !enabled }, false);
    try {
      mutate(await setEmailIntake(!enabled), false);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "บันทึกไม่สำเร็จ");
      mutate(); // ดึงค่าจริงกลับมา อย่าปล่อยให้หน้าเว็บโกหกว่าเปลี่ยนแล้ว
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="glass-card rounded-2xl p-md space-y-sm">
      <div className="flex items-center gap-xs text-on-surface">
        <Mail className="w-5 h-5 text-primary" />
        <h2 className="text-headline-md">การเชื่อมต่อกล่องอีเมล</h2>
      </div>

      {/* สวิตช์ */}
      <div className="flex items-center justify-between gap-sm p-sm rounded-xl border border-outline/30">
        <div className="min-w-0">
          <p className="text-label-md font-semibold text-on-surface">
            {enabled ? "เปิดอยู่ — ระบบกำลังเฝ้ากล่องอีเมล" : "ปิดอยู่"}
          </p>
          <p className="text-label-sm text-on-surface-variant leading-snug">
            {configured
              ? "ปิดแล้วระบบจะไม่เชื่อมต่อกล่องอีเมลเลย"
              : "ยังไม่ได้ตั้งค่า IMAP ในระบบ ติดต่อผู้ดูแล"}
          </p>
        </div>
        <button
          role="switch"
          aria-checked={enabled}
          aria-label="เปิดหรือปิดการรับใบสมัครทางอีเมล"
          onClick={toggle}
          disabled={!isAdmin || !configured || busy || !data}
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

      {!isAdmin && data && (
        <p className="text-label-sm text-on-surface-variant">บัญชีทดลองเปลี่ยนการตั้งค่านี้ไม่ได้</p>
      )}
      {saveError && (
        <p className="text-error text-label-md" role="alert">
          {saveError}
        </p>
      )}
      {error && !data && (
        <p className="text-error text-label-md" role="alert">
          อ่านสถานะไม่สำเร็จ — ลองรีเฟรชหน้าอีกครั้ง
        </p>
      )}

      {/* สถานะจากการทำงานจริง */}
      {data && (
        <div className="grid gap-sm sm:grid-cols-3">
          <Stat label="ตรวจกล่องล่าสุด" value={formatTime(data.last_poll_at)} />
          <Stat label="รับเข้าวันนี้" value={`${data.matched_count_today} ฉบับ`} />
          <Stat
            label="ไม่ได้รับเข้าวันนี้"
            value={`${data.unmatched_count_today} ฉบับ`}
            hint={
              data.unmatched_count_today > 0
                ? "จับคู่ตำแหน่งงานไม่ได้ หรือไม่มีไฟล์แนบ — ยังอยู่ในกล่องอีเมล"
                : undefined
            }
          />
        </div>
      )}

      {data?.last_error && (
        <Notice tone="error" icon="error" title="เชื่อมต่อกล่องอีเมลไม่สำเร็จ">
          <p className="text-on-surface-variant text-label-sm leading-snug break-words">
            {data.last_error}
          </p>
        </Notice>
      )}

      {/* วิธีใช้ — โชว์ที่อยู่จริงที่ backend คืนมา ไม่ใช่ตัวอย่างสมมติ */}
      {data?.apply_address_template && (
        <Notice tone="primary" icon="info" title="ให้ผู้สมัครส่งเรซูเม่ (PDF) มาที่">
          <p className="text-on-surface text-label-md font-mono break-all mt-0.5">
            {data.apply_address_template.replace("{job_id}", "<รหัสงาน>")}
          </p>
          <p className="text-on-surface-variant text-label-sm leading-snug mt-1">
            ดูที่อยู่พร้อมรหัสงานจริงได้ที่หน้ารายละเอียดของแต่ละตำแหน่ง (คัดลอกได้เลย)
          </p>
        </Notice>
      )}

      {/* ข้อควรรู้ — เดิมเป็นกล่องเตือนสีเหลืองสองกล่องใหญ่ ซึ่งแย่งสายตาจากสวิตช์
          ทั้งที่ไม่ใช่ปัญหาที่ต้องแก้ เป็นแค่ข้อเท็จจริงของระบบ ยุบเป็นรายการเล็กบรรทัดเดียวต่อข้อ */}
      <ul className="space-y-1 text-label-sm text-on-surface-variant">
        <li className="flex gap-xs items-start">
          <span className="material-symbols-outlined text-[16px] text-outline flex-none mt-0.5">
            mark_email_read
          </span>
          <span>
            ระบบ<b className="text-on-surface">ไม่ตอบกลับผู้สมัครเอง</b> — อีเมลตอบกลับทุกฉบับยังต้องให้คุณตรวจและกดส่ง
          </span>
        </li>
        <li className="flex gap-xs items-start">
          <span className="material-symbols-outlined text-[16px] text-outline flex-none mt-0.5">
            toggle_off
          </span>
          <span>ค่าเริ่มต้นคือปิด — ขณะปิด ระบบไม่เชื่อมต่อกล่องอีเมลเลย</span>
        </li>
      </ul>
    </section>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="p-sm rounded-xl bg-glass/30 border border-outline/20">
      <p className="text-label-sm text-on-surface-variant">{label}</p>
      <p className="text-label-md font-semibold text-on-surface mt-0.5">{value}</p>
      {hint && (
        <p className="text-label-sm text-outline leading-snug mt-0.5">{hint}</p>
      )}
    </div>
  );
}

/**
 * สูตร notice เดิมจาก components/file-upload.tsx
 * ⚠️ ตัวอักษรต้องเป็น on-surface / on-surface-variant เสมอ ห้ามใช้สีโทน
 * เพราะตระกูล *-fixed ตั้งใจให้เหมือนกันทั้งสองธีม พอวางบนพื้นมืดแล้วอ่านไม่ออก
 */
function Notice({
  tone,
  icon,
  title,
  children,
}: {
  tone: "tertiary" | "primary" | "error";
  icon: string;
  title: string;
  children?: React.ReactNode;
}) {
  const wrap = {
    tertiary: "border-tertiary/30 bg-tertiary-container/10",
    primary: "border-primary/30 bg-primary-container/10",
    error: "border-error/30 bg-error-container/10",
  }[tone];
  const iconTone = {
    tertiary: "text-tertiary",
    primary: "text-primary",
    error: "text-error",
  }[tone];

  return (
    <div className={`p-sm rounded-xl border flex gap-xs items-start ${wrap}`}>
      <span
        className={`material-symbols-outlined text-[20px] flex-none ${iconTone}`}
        style={{ fontVariationSettings: "'FILL' 1" }}
      >
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-on-surface text-label-md font-semibold leading-snug">
          {title}
        </p>
        {children}
      </div>
    </div>
  );
}

function formatTime(iso: string | null): string {
  if (!iso) return "ยังไม่เคยตรวจ";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "ยังไม่เคยตรวจ";
  return d.toLocaleString("th-TH", { dateStyle: "short", timeStyle: "short" });
}
