"use client";

import { useState } from "react";
import ConfirmDialog from "@/components/confirm-dialog";
import { setStage } from "@/lib/api";
import type { InterviewResult } from "@/lib/types";

/**
 * การ์ด "ขั้นถัดไปหลังสัมภาษณ์" — เปลี่ยนตามผลสัมภาษณ์ที่บันทึกไว้
 *
 * เดิมเป็นการ์ดรับเข้าเป็นพนักงานใบเดียวที่ดูแค่ว่าถึงขั้น "สัมภาษณ์แล้ว" หรือยัง พอ HR
 * บันทึกผลว่าไม่ผ่าน การ์ดก็ยังถาม "สัมภาษณ์ผ่านแล้ว?" แล้วเสนอแต่ปุ่มจ้าง ซึ่งขัดกับผล
 * ที่เพิ่งบันทึกไปตรง ๆ และไม่มีทางปิดกระบวนการให้กด
 *
 * - ไม่ผ่าน → ปุ่มหลักคือปิดกระบวนการ (ย้ายไป "ไม่ไปต่อ") · ยังจ้างได้จากลิงก์เล็ก
 *   เพราะคนตัดสินสุดท้ายคือ HR ไม่ใช่ผลที่กรอกไว้
 * - สำรอง → จ้างเป็นปุ่มหลัก ปิดกระบวนการเป็นปุ่มรอง
 * - ผ่าน / ยังไม่บันทึกผล → การ์ดจ้างแบบเดิม
 *
 * ย้ายขั้นผ่าน setStage ตัวเดียวกับไทม์ไลน์และกระดาน · ไม่ส่งอีเมลใด ๆ ให้เอง
 */
export default function HireOrCloseCard({
  candidateId,
  result,
  onHire,
  onChanged,
}: {
  candidateId: string;
  result: InterviewResult | null;
  onHire: () => void;
  onChanged: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function close() {
    setBusy(true);
    setError(null);
    try {
      await setStage(candidateId, "declined");
      setConfirming(false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "ย้ายขั้นไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  const hireButton = (
    <button
      onClick={onHire}
      className="btn-primary text-body-md px-md py-sm rounded-xl shadow-lg shadow-primary/30 hover:-translate-y-0.5 transition-all"
    >
      <span
        className="material-symbols-outlined text-[22px]"
        style={{ fontVariationSettings: "'FILL' 1" }}
      >
        person_add
      </span>
      รับเข้าเป็นพนักงาน
    </button>
  );

  const closeButton = (primary: boolean) => (
    <button
      onClick={() => setConfirming(true)}
      className={primary ? "btn-tonal px-md py-sm rounded-xl" : "btn-secondary-glass"}
    >
      <span className="material-symbols-outlined text-[18px]">block</span>
      ย้ายไป “ไม่ไปต่อ”
    </button>
  );

  return (
    <div className="glass-card rounded-2xl p-md space-y-xs">
      {result === "fail" ? (
        <>
          <div className="flex items-center justify-between gap-sm flex-wrap">
            <div>
              <h3 className="text-headline-md text-on-surface flex items-center gap-xs">
                <span className="material-symbols-outlined text-error">cancel</span>
                สัมภาษณ์ไม่ผ่าน
              </h3>
              <p className="text-label-md text-on-surface-variant mt-0.5">
                ปิดกระบวนการของผู้สมัครรายนี้ — การ์ดบนกระดานจะย้ายไป “ไม่ไปต่อ”
              </p>
            </div>
            {closeButton(true)}
          </div>
          <button
            onClick={onHire}
            className="text-label-sm text-on-surface-variant hover:text-primary hover:underline"
          >
            ยังต้องการรับเข้า? รับเข้าเป็นพนักงาน
          </button>
        </>
      ) : (
        <div className="flex items-center justify-between gap-sm flex-wrap">
          <div>
            <h3 className="text-headline-md text-on-surface flex items-center gap-xs">
              <span className="material-symbols-outlined text-primary">badge</span>
              รับเข้าเป็นพนักงาน
            </h3>
            <p className="text-label-md text-on-surface-variant mt-0.5">
              {result === "standby"
                ? "ผลสัมภาษณ์เป็นสำรอง — รับเข้าเมื่อตัดสินใจแล้ว หรือปิดกระบวนการถ้าไม่รับ"
                : result === "pass"
                  ? "สัมภาษณ์ผ่านแล้ว — บันทึกเข้าทะเบียนพนักงานเพื่อติดตามสถานะย้อนหลังได้"
                  : "สัมภาษณ์ผ่านแล้ว? บันทึกเข้าทะเบียนพนักงานเพื่อติดตามสถานะย้อนหลังได้"}
            </p>
          </div>
          <div className="flex items-center gap-xs flex-wrap">
            {result === "standby" && closeButton(false)}
            {hireButton}
          </div>
        </div>
      )}

      {error && !confirming && (
        <p className="text-error text-label-md" role="alert">
          {error}
        </p>
      )}

      {confirming && (
        <ConfirmDialog
          title="ปิดกระบวนการของผู้สมัครรายนี้?"
          body={
            <p>
              ผู้สมัครจะย้ายไปขั้น “ไม่ไปต่อ” บนกระดาน ดึงกลับเข้ากระบวนการได้ภายหลังจาก
              เส้นทางของผู้สมัคร · ระบบไม่ส่งอีเมลใด ๆ ให้เอง
            </p>
          }
          confirmLabel="ย้ายไป “ไม่ไปต่อ”"
          busy={busy}
          error={error}
          onConfirm={close}
          onClose={() => {
            setConfirming(false);
            setError(null);
          }}
        />
      )}
    </div>
  );
}
