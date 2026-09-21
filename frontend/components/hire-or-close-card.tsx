"use client";

import { useState } from "react";
import ConfirmDialog from "@/components/confirm-dialog";
import OfferDialog from "@/components/offer-dialog";
import { respondOffer, setStage } from "@/lib/api";
import { isOfferOverdue, localToday } from "@/lib/offer";
import type { InterviewResult, JobOffer } from "@/lib/types";

/**
 * การ์ด "ขั้นถัดไปหลังสัมภาษณ์" — ยื่นข้อเสนอ → รอคำตอบ → รับเข้าเป็นพนักงาน / ปิดกระบวนการ
 *
 * โผล่เฉพาะขั้น "สัมภาษณ์แล้ว" กับ "ยื่นข้อเสนอ" (หน้าแม่เป็นคนกรอง) · เปลี่ยนตามสถานะ:
 *
 * | ขั้น / ผล                       | การ์ด                                                   |
 * |--------------------------------|--------------------------------------------------------|
 * | สัมภาษณ์ ผ่าน / ยังไม่บันทึกผล   | ยื่นข้อเสนอ (หลัก) · รับเข้าเลย (ลิงก์ — ตกลงกันในห้องแล้ว)  |
 * | สัมภาษณ์ สำรอง                  | ยื่นข้อเสนอ (หลัก) · ไม่ไปต่อ (รอง)                       |
 * | สัมภาษณ์ ไม่ผ่าน                 | ปิดกระบวนการ (หลัก) · ยังจ้างได้จากลิงก์                   |
 * | ยื่นข้อเสนอ รอคำตอบ              | สรุปข้อเสนอ + เลยกำหนด · ผู้สมัครตอบรับ / ปฏิเสธ            |
 * | ยื่นข้อเสนอ ตอบรับแล้ว           | รับเข้าเป็นพนักงาน                                        |
 * | ยื่นข้อเสนอ แต่ไม่มีรายละเอียด    | บันทึกข้อเสนอ · ตอบรับ→รับเข้า / ปฏิเสธ→ไม่ไปต่อ ตรง ๆ     |
 *
 * ⚠️ ผู้สมัครตอบรับ **ไม่ใช่การจ้าง** — บันทึกคำตอบแล้วเปิดหน้าต่างรับเข้าให้ HR กดยืนยันเอง
 * (ระเบียนพนักงานเป็นของถาวร) · ย้ายขั้นทุกทางผ่าน endpoint เดียวกับไทม์ไลน์และกระดาน
 * ไม่มีทางไหนส่งอีเมลให้เอง
 */
export default function HireOrCloseCard({
  candidateId,
  candidateName,
  jobTitle,
  boardStage,
  result,
  offer,
  onHire,
  onChanged,
}: {
  candidateId: string;
  candidateName: string;
  jobTitle: string;
  boardStage: "interviewed" | "offer";
  result: InterviewResult | null;
  offer: JobOffer | null;
  onHire: () => void;
  onChanged: () => void;
}) {
  const [showOffer, setShowOffer] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);
  const [confirmDecline, setConfirmDecline] = useState(false);
  const [declineReason, setDeclineReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>, after?: () => void) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setConfirmClose(false);
      setConfirmDecline(false);
      onChanged();
      after?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "บันทึกไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  // ตอบรับ = บันทึกคำตอบก่อน แล้วค่อยเปิดหน้าต่างรับเข้า (ซึ่งเติมค่าจากข้อเสนอให้)
  // ไม่มีข้อเสนอที่บันทึกไว้ก็ไม่มีคำตอบให้บันทึก — เปิดหน้าต่างรับเข้าเลย
  const accept = () =>
    offer ? run(() => respondOffer(candidateId, "accepted"), onHire) : onHire();

  // ปฏิเสธ = มีข้อเสนอ → บันทึกคำตอบ (backend ย้ายไป "ไม่ไปต่อ" ให้) · ไม่มี → ย้ายขั้นตรง ๆ
  const decline = () =>
    offer
      ? run(() => respondOffer(candidateId, "declined", declineReason.trim() || undefined))
      : run(() => setStage(candidateId, "declined"));

  const hireButton = (label = "รับเข้าเป็นพนักงาน") => (
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
      {label}
    </button>
  );

  const offerButton = (
    <button
      onClick={() => setShowOffer(true)}
      className="btn-primary text-body-md px-md py-sm rounded-xl shadow-lg shadow-primary/30 hover:-translate-y-0.5 transition-all"
    >
      <span className="material-symbols-outlined text-[22px]">handshake</span>
      ยื่นข้อเสนอ
    </button>
  );

  const closeButton = (primary: boolean) => (
    <button
      onClick={() => setConfirmClose(true)}
      className={primary ? "btn-tonal px-md py-sm rounded-xl" : "btn-secondary-glass"}
    >
      <span className="material-symbols-outlined text-[18px]">block</span>
      ย้ายไป “ไม่ไปต่อ”
    </button>
  );

  const textLink = (label: string, onClick: () => void) => (
    <button
      onClick={onClick}
      className="text-label-sm text-on-surface-variant hover:text-primary hover:underline"
    >
      {label}
    </button>
  );

  return (
    <div className="glass-card rounded-2xl p-md space-y-xs">
      {boardStage === "offer" ? (
        <OfferStage
          offer={offer}
          busy={busy}
          onAccept={accept}
          onDecline={() => setConfirmDecline(true)}
          onEditOffer={() => setShowOffer(true)}
          hireButton={hireButton}
        />
      ) : result === "fail" ? (
        <>
          <Header
            icon="cancel"
            iconClass="text-error"
            title="สัมภาษณ์ไม่ผ่าน"
            subtitle="ปิดกระบวนการของผู้สมัครรายนี้ — การ์ดบนกระดานจะย้ายไป “ไม่ไปต่อ”"
            actions={closeButton(true)}
          />
          {textLink("ยังต้องการรับเข้า? รับเข้าเป็นพนักงาน", onHire)}
        </>
      ) : (
        <>
          <Header
            icon="handshake"
            iconClass="text-primary"
            title="ยื่นข้อเสนอ"
            subtitle={
              result === "standby"
                ? "ผลสัมภาษณ์เป็นสำรอง — ยื่นข้อเสนอเมื่อตัดสินใจแล้ว หรือปิดกระบวนการถ้าไม่รับ"
                : "บันทึกตำแหน่ง เงินเดือน วันเริ่มงาน และวันที่ต้องตอบ — ตอนรับเข้าจะเติมให้เอง"
            }
            actions={
              <>
                {result === "standby" && closeButton(false)}
                {offerButton}
              </>
            }
          />
          {textLink("ตกลงกันแล้วในห้องสัมภาษณ์? รับเข้าเป็นพนักงานเลย", onHire)}
        </>
      )}

      {error && !confirmClose && !confirmDecline && (
        <p className="text-error text-label-md" role="alert">
          {error}
        </p>
      )}

      {showOffer && (
        <OfferDialog
          candidateId={candidateId}
          candidateName={candidateName}
          defaultPosition={jobTitle}
          existing={offer}
          onSaved={() => {
            setShowOffer(false);
            onChanged();
          }}
          onClose={() => setShowOffer(false)}
        />
      )}

      {confirmClose && (
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
          onConfirm={() => run(() => setStage(candidateId, "declined"))}
          onClose={() => {
            setConfirmClose(false);
            setError(null);
          }}
        />
      )}

      {confirmDecline && (
        <ConfirmDialog
          title="ผู้สมัครปฏิเสธข้อเสนอ?"
          body={
            <div className="space-y-xs">
              <p>
                ผู้สมัครจะย้ายไปขั้น “ไม่ไปต่อ” ดึงกลับได้ภายหลังจากเส้นทางของผู้สมัคร ·
                ระบบไม่ส่งอีเมลใด ๆ ให้เอง
              </p>
              {offer && (
                <label className="block space-y-xs">
                  <span className="text-label-sm text-outline">
                    เหตุผล (ไม่บังคับ — เก็บไว้ดูภายใน ไม่ได้ส่งถึงผู้สมัคร)
                  </span>
                  <input
                    className="input-glass w-full"
                    value={declineReason}
                    onChange={(e) => setDeclineReason(e.target.value)}
                    placeholder="เช่น เงินเดือนไม่ถึง หรือได้งานที่อื่น"
                    maxLength={1000}
                    disabled={busy}
                  />
                </label>
              )}
            </div>
          }
          confirmLabel="บันทึกว่าปฏิเสธ"
          busy={busy}
          error={error}
          onConfirm={decline}
          onClose={() => {
            setConfirmDecline(false);
            setError(null);
          }}
        />
      )}
    </div>
  );
}

/** หัวการ์ด: ไอคอน + หัวข้อ + คำอธิบาย ทางซ้าย ปุ่มทางขวา (ตกลงบรรทัดใหม่เมื่อจอแคบ) */
function Header({
  icon,
  iconClass,
  title,
  subtitle,
  actions,
}: {
  icon: string;
  iconClass: string;
  title: string;
  subtitle: React.ReactNode;
  actions: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-sm flex-wrap">
      <div className="min-w-0">
        <h3 className="text-headline-md text-on-surface flex items-center gap-xs">
          <span className={`material-symbols-outlined ${iconClass}`}>{icon}</span>
          {title}
        </h3>
        <div className="text-label-md text-on-surface-variant mt-0.5">{subtitle}</div>
      </div>
      <div className="flex items-center gap-xs flex-wrap">{actions}</div>
    </div>
  );
}

function fmtDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString("th-TH", { dateStyle: "medium" });
}

/** ขั้นยื่นข้อเสนอ — รอคำตอบ / ตอบรับแล้ว / ยังไม่มีรายละเอียด */
function OfferStage({
  offer,
  busy,
  onAccept,
  onDecline,
  onEditOffer,
  hireButton,
}: {
  offer: JobOffer | null;
  busy: boolean;
  onAccept: () => void;
  onDecline: () => void;
  onEditOffer: () => void;
  hireButton: (label?: string) => React.ReactNode;
}) {
  const respondButtons = (
    <>
      <button onClick={onDecline} disabled={busy} className="btn-secondary-glass">
        <span className="material-symbols-outlined text-[18px]">block</span>
        ผู้สมัครปฏิเสธ
      </button>
      <button
        onClick={onAccept}
        disabled={busy}
        className="btn-primary text-body-md px-md py-sm rounded-xl shadow-lg shadow-primary/30"
      >
        <span className="material-symbols-outlined text-[20px]">how_to_reg</span>
        ผู้สมัครตอบรับ
      </button>
    </>
  );

  // ลากการ์ดมาขั้นยื่นข้อเสนอบนกระดานโดยไม่บันทึกรายละเอียด — ยังตอบรับ/ปฏิเสธได้ตามปกติ
  if (!offer) {
    return (
      <>
        <Header
          icon="handshake"
          iconClass="text-primary"
          title="ยื่นข้อเสนอแล้ว"
          subtitle="ยังไม่ได้บันทึกรายละเอียดข้อเสนอ — บันทึกไว้แล้วตอนรับเข้าจะเติมให้เอง"
          actions={respondButtons}
        />
        <button
          onClick={onEditOffer}
          className="text-label-sm text-primary hover:underline"
        >
          บันทึกรายละเอียดข้อเสนอ
        </button>
      </>
    );
  }

  const accepted = offer.response === "accepted";
  const overdue = isOfferOverdue(offer, localToday());

  return (
    <>
      <Header
        icon={accepted ? "how_to_reg" : "hourglass_top"}
        iconClass={accepted ? "text-secondary" : "text-primary"}
        title={accepted ? "ผู้สมัครตอบรับข้อเสนอแล้ว" : "รอผู้สมัครตอบรับข้อเสนอ"}
        subtitle={
          accepted
            ? "บันทึกเข้าทะเบียนพนักงาน — ค่าจากข้อเสนอจะถูกเติมให้"
            : offer.response === "declined"
              ? "ผู้สมัครเคยปฏิเสธข้อเสนอนี้ — แก้ข้อเสนอเพื่อยื่นใหม่ หรือบันทึกคำตอบใหม่"
              : "ติดต่อผู้สมัครนอกระบบได้ตามปกติ แล้วบันทึกคำตอบที่นี่"
        }
        actions={accepted ? hireButton() : respondButtons}
      />

      {/* สรุปข้อเสนอ — ⚠️ เงินเดือนเป็นข้อมูลอ่อนไหว แสดงบนจอได้ ห้ามใส่ใน URL/log */}
      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-xs p-sm rounded-xl bg-glass/40 text-label-md">
        <OfferField label="ตำแหน่ง" value={offer.position} />
        <OfferField
          label="เงินเดือน"
          value={
            offer.salary != null
              ? `${Number(offer.salary).toLocaleString("th-TH")} บาท`
              : "—"
          }
        />
        <OfferField
          label="เริ่มงาน"
          value={offer.start_date ? fmtDate(offer.start_date) : "—"}
        />
        <OfferField
          label="ตอบภายใน"
          value={
            offer.respond_by ? (
              <span className="inline-flex items-center gap-1 flex-wrap">
                {fmtDate(offer.respond_by)}
                {overdue && (
                  <span className="text-label-sm font-semibold px-2 py-0.5 rounded-full bg-error-container/50 text-on-error-container">
                    เลยกำหนดแล้ว
                  </span>
                )}
              </span>
            ) : (
              "—"
            )
          }
        />
      </dl>
      {offer.note && (
        <p className="text-label-md text-on-surface-variant whitespace-pre-wrap">{offer.note}</p>
      )}
      <button onClick={onEditOffer} className="text-label-sm text-primary hover:underline">
        แก้ข้อเสนอ
      </button>
    </>
  );
}

function OfferField({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-label-sm text-outline">{label}</dt>
      <dd className="text-on-surface break-words">{value}</dd>
    </div>
  );
}
