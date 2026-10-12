"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import Breadcrumb from "@/components/breadcrumb";
import EmailIntakeCard from "@/components/email-intake-card";
import { useIntakeFeed } from "@/components/intake-notifications";
import { INTAKE_OUTCOME, type EmailIntakeActivityItem } from "@/lib/types";
import Spinner from "@/components/spinner";

type Filter = "all" | "matched" | "attention";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "ทั้งหมด" },
  { key: "matched", label: "รับเข้าแล้ว" },
  { key: "attention", label: "ต้องจัดการเอง" },
];

/**
 * หน้า "รับสมัครทางอีเมล" — เดิมเป็นการ์ดหนึ่งในหน้าตั้งค่า
 * ย้ายมาเป็นเมนูหลักเพราะเป็นงานประจำวัน (ดูว่าวันนี้มีใครส่งมา) ไม่ใช่การตั้งค่าครั้งเดียว
 *
 * บนลงล่าง: ความเคลื่อนไหวก่อน (สิ่งที่ HR เข้ามาดูบ่อยที่สุด) แล้วค่อยสวิตช์/สถานะ
 */
export default function IntakePage() {
  const { items, error, seenAt, markAllSeen } = useIntakeFeed();
  const [filter, setFilter] = useState<Filter>("all");

  // จำเส้น "ใหม่" ไว้ตั้งแต่ตอนเปิดหน้า แล้วค่อย mark อ่านแล้ว —
  // ถ้าใช้ seenAt สด ป้าย "ใหม่" จะหายทันทีที่เปิดหน้า HR จะไม่รู้ว่าอันไหนเพิ่งมา
  const openedSeenAt = useRef<number | null>(null);
  useEffect(() => {
    if (openedSeenAt.current === null && seenAt > 0) openedSeenAt.current = seenAt;
  }, [seenAt]);
  useEffect(() => {
    if (items && seenAt > 0) markAllSeen();
    // ต้อง mark ทุกครั้งที่มีของเข้ามาใหม่ระหว่างเปิดหน้านี้อยู่ด้วย
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  const visible = (items ?? []).filter((i) =>
    filter === "all"
      ? true
      : filter === "matched"
        ? i.outcome === "matched"
        : INTAKE_OUTCOME[i.outcome].needsAction,
  );
  const attentionCount = (items ?? []).filter(
    (i) => INTAKE_OUTCOME[i.outcome].needsAction,
  ).length;

  return (
    <div className="space-y-md">
      <Breadcrumb items={[{ label: "รับสมัครทางอีเมล" }]} />

      <div>
        <h1 className="text-headline-lg text-on-surface">รับสมัครทางอีเมล</h1>
        <p className="text-body-md text-on-surface-variant mt-1">
          ระบบอ่านกล่องอีเมลรับสมัครเป็นระยะ แล้วดึงเรซูเม่ที่แนบมาเข้าคิววิเคราะห์ให้เอง
          มีใบสมัครใหม่เมื่อไรจะแจ้งเตือนที่มุมขวาล่างและบนเมนูนี้
        </p>
      </div>

      <div className="grid gap-md grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(0,1fr)_22rem] items-start">
        {/* ความเคลื่อนไหว */}
        <section className="glass-card rounded-2xl p-md space-y-sm" aria-labelledby="feed-h">
          <div className="flex flex-wrap items-center justify-between gap-sm">
            <h2 id="feed-h" className="text-headline-md text-on-surface">
              ความเคลื่อนไหวล่าสุด
            </h2>
            <div role="tablist" aria-label="กรองรายการ" className="flex gap-1 p-1 rounded-lg bg-glass/40">
              {FILTERS.map((f) => (
                <button
                  key={f.key}
                  role="tab"
                  aria-selected={filter === f.key}
                  onClick={() => setFilter(f.key)}
                  className={`px-sm py-1 rounded-md text-label-md transition-colors ${
                    filter === f.key
                      ? "bg-primary/15 text-primary font-semibold"
                      : "text-on-surface-variant hover:text-on-surface"
                  }`}
                >
                  {f.label}
                  {f.key === "attention" && attentionCount > 0 && ` (${attentionCount})`}
                </button>
              ))}
            </div>
          </div>

          {error && !items ? (
            <p className="text-error text-label-md" role="alert">
              โหลดรายการไม่สำเร็จ — ลองรีเฟรชหน้าอีกครั้ง
            </p>
          ) : !items ? (
            <p className="text-outline text-label-md flex items-center gap-xs" role="status">
          <Spinner className="text-[18px]" />
          กำลังโหลด…
        </p>
          ) : visible.length === 0 ? (
            <EmptyFeed filter={filter} />
          ) : (
            <ul className="divide-y divide-outline-variant/40">
              {visible.map((i) => (
                <FeedRow
                  key={i.id}
                  item={i}
                  isNew={
                    openedSeenAt.current !== null &&
                    new Date(i.created_at).getTime() > openedSeenAt.current
                  }
                />
              ))}
            </ul>
          )}
        </section>

        <EmailIntakeCard />
      </div>
    </div>
  );
}

function FeedRow({ item, isNew }: { item: EmailIntakeActivityItem; isNew: boolean }) {
  const meta = INTAKE_OUTCOME[item.outcome];
  const matched = item.outcome === "matched";
  const href =
    matched && item.job_id && item.candidate_id
      ? `/jobs/${item.job_id}/candidates/${item.candidate_id}`
      : null;
  const iconTone = matched
    ? "text-primary"
    : meta.needsAction
      ? "text-tertiary"
      : "text-outline";

  const title = matched
    ? (item.candidate_name ?? "ผู้สมัคร (ถูกลบไปแล้ว)")
    : (item.from_addr ?? "ไม่ทราบผู้ส่ง");

  return (
    <li className="py-sm flex gap-sm items-start">
      <span
        className={`material-symbols-outlined text-[22px] flex-none mt-0.5 ${iconTone}`}
        style={{ fontVariationSettings: "'FILL' 1" }}
        aria-hidden
      >
        {meta.icon}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-xs flex-wrap">
          {href ? (
            <Link href={href} className="text-label-md font-semibold text-on-surface hover:text-primary hover:underline truncate">
              {title}
            </Link>
          ) : (
            <span className="text-label-md font-semibold text-on-surface truncate">{title}</span>
          )}
          {isNew && (
            <span className="px-1.5 rounded-full bg-primary text-on-primary text-label-sm font-bold">
              ใหม่
            </span>
          )}
        </div>

        <p className="text-label-sm text-on-surface-variant">
          {meta.label}
          {item.job_title && <> · {item.job_title}</>}
        </p>

        {/* บอกทางออกให้ของที่ต้องจัดการเอง — ไม่งั้น HR รู้ว่ามีปัญหาแต่ไม่รู้จะทำอะไร */}
        {meta.needsAction && (
          <p className="text-label-sm text-outline mt-0.5 break-words">
            {item.subject && <>หัวข้อ “{item.subject}” · </>}
            {nextStep(item)}
          </p>
        )}
      </div>

      <time
        dateTime={item.created_at}
        title={new Date(item.created_at).toLocaleString("th-TH")}
        className="text-label-sm text-outline flex-none whitespace-nowrap"
      >
        {relativeTime(item.created_at)}
      </time>
    </li>
  );
}

function nextStep(item: EmailIntakeActivityItem): string {
  switch (item.outcome) {
    case "unmatched":
      return "เปิดอีเมลในกล่อง แล้วอัปโหลดไฟล์เข้าตำแหน่งที่ถูกต้องเอง";
    case "no_attachment":
      return "อาจต้องติดต่อผู้สมัครให้แนบเรซูเม่เป็น PDF";
    case "unreadable":
      return "ไฟล์ไม่มีข้อความให้อ่าน — ขอไฟล์ PDF ที่ไม่ใช่ภาพสแกน";
    case "job_closed":
      return "เปิดรับตำแหน่งอีกครั้ง หรือแจ้งผู้สมัครว่าปิดรับแล้ว";
    case "error":
      return item.detail ?? "ลองตรวจสถานะการเชื่อมต่อด้านขวา";
    default:
      return "";
  }
}

function EmptyFeed({ filter }: { filter: Filter }) {
  const text =
    filter === "attention"
      ? "ไม่มีอีเมลที่ต้องจัดการเอง"
      : filter === "matched"
        ? "ยังไม่มีใบสมัครที่รับเข้าระบบทางอีเมล"
        : "ยังไม่มีอีเมลเข้ามา — เปิดการเชื่อมต่อด้านขวา แล้วประกาศที่อยู่รับสมัครจากหน้าตำแหน่งงาน";
  return (
    <div className="py-lg flex flex-col items-center text-center gap-xs">
      <span className="material-symbols-outlined text-[40px] text-outline" aria-hidden>
        inbox
      </span>
      <p className="text-label-md text-on-surface-variant max-w-sm">{text}</p>
    </div>
  );
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const min = Math.round(diff / 60_000);
  if (min < 1) return "เมื่อสักครู่";
  if (min < 60) return `${min} นาทีที่แล้ว`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} ชม.ที่แล้ว`;
  return new Date(iso).toLocaleDateString("th-TH", { day: "numeric", month: "short" });
}
