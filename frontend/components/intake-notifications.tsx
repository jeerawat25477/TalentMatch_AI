"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import useSWR from "swr";
import { getEmailIntakeActivity } from "@/lib/api";
import { INTAKE_OUTCOME, type EmailIntakeActivityItem } from "@/lib/types";

/**
 * การแจ้งเตือนใบสมัครที่เข้ามาทางอีเมล — สามชั้น จากเบาไปหนัก:
 *   1. ตัวเลขบนเมนู "รับสมัครทางอีเมล" (ค้างไว้จนกว่าจะเปิดหน้านั้น)
 *   2. เลข (n) หน้าชื่อแท็บ — เห็นได้แม้ HR เปิดแท็บอื่นอยู่
 *   3. toast มุมขวาล่าง เฉพาะของที่เพิ่งเข้ามา "ระหว่างที่เปิดหน้าเว็บอยู่"
 *
 * "อ่านแล้ว" จำเป็นเวลาไว้ใน localStorage ไม่ใช่ใน DB — ตอนนี้มี HR คนเดียว
 * (ดู docstring ของ GET /settings/email-intake/activity)
 *
 * ⚠️ ห้ามยิง toast ให้ของที่มีอยู่แล้วตอนโหลดหน้าครั้งแรก ไม่งั้นทุกครั้งที่รีเฟรช
 * จะมี toast ของเก่าเด้งซ้ำ แล้ว HR จะเรียนรู้ที่จะเมินมัน
 */

const SEEN_KEY = "tm-intake-seen-at";
const POLL_MS = 30_000;
const TOAST_MS = 8_000;

interface Toast {
  key: string;
  title: string;
  body: string;
  href: string;
  icon: string;
  attention: boolean;
}

interface IntakeFeed {
  items: EmailIntakeActivityItem[] | undefined;
  error: unknown;
  /** เวลาที่เปิดดูฟีดล่าสุด (ms) — ของที่ใหม่กว่านี้ถือว่ายังไม่ได้อ่าน */
  seenAt: number;
  unreadCount: number;
  markAllSeen: () => void;
}

const Ctx = createContext<IntakeFeed | null>(null);

export function useIntakeFeed(): IntakeFeed {
  const v = useContext(Ctx);
  if (!v) throw new Error("useIntakeFeed ต้องอยู่ใต้ IntakeNotificationsProvider");
  return v;
}

function readSeen(): number | null {
  try {
    const raw = localStorage.getItem(SEEN_KEY);
    return raw ? Number(raw) || null : null;
  } catch {
    return null;
  }
}

function writeSeen(ms: number) {
  try {
    localStorage.setItem(SEEN_KEY, String(ms));
  } catch {
    /* เขียนไม่ได้ก็แค่ตัวเลขไม่ลดหลังรีเฟรช */
  }
}

const ts = (i: EmailIntakeActivityItem) => new Date(i.created_at).getTime();

export function IntakeNotificationsProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const { data: items, error } = useSWR(
    "/api/v1/settings/email-intake/activity",
    () => getEmailIntakeActivity(30),
    { refreshInterval: POLL_MS },
  );

  const [seenAt, setSeenAt] = useState(0);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const knownIds = useRef<Set<string> | null>(null);

  // ครั้งแรกที่ใช้งาน (ไม่เคยจำเวลาไว้) ถือว่าประวัติเก่าอ่านแล้วทั้งหมด —
  // ไม่งั้นเปิดมาเจอเลข 30 ตั้งแต่วันแรกทั้งที่ไม่มีอะไรใหม่
  useEffect(() => {
    const saved = readSeen();
    if (saved) {
      setSeenAt(saved);
    } else {
      const now = Date.now();
      writeSeen(now);
      setSeenAt(now);
    }
  }, []);

  const markAllSeen = useCallback(() => {
    const newest = items?.length ? Math.max(...items.map(ts)) : 0;
    const next = Math.max(Date.now(), newest);
    writeSeen(next);
    setSeenAt(next);
  }, [items]);

  const unreadCount = useMemo(
    () => (items ?? []).filter((i) => ts(i) > seenAt && i.outcome !== "duplicate").length,
    [items, seenAt],
  );

  // หาของที่เพิ่งโผล่ในรอบ poll นี้ → toast
  useEffect(() => {
    if (!items) return;
    if (knownIds.current === null) {
      knownIds.current = new Set(items.map((i) => i.id)); // baseline — ไม่ toast
      return;
    }
    const fresh = items.filter(
      (i) => !knownIds.current!.has(i.id) && i.outcome !== "duplicate",
    );
    items.forEach((i) => knownIds.current!.add(i.id));
    // อยู่หน้าฟีดอยู่แล้ว เห็นรายการเด้งขึ้นเองอยู่แล้ว ไม่ต้อง toast ซ้อน
    if (!fresh.length || pathname.startsWith("/intake")) return;

    setToasts((prev) => [...prev, ...buildToasts(fresh)].slice(-3));
  }, [items, pathname]);

  // ตัวเลขหน้าชื่อแท็บ — เก็บชื่อเดิมไว้ก่อนเติม กันเลขซ้อนกันเป็น (2) (1) ...
  useEffect(() => {
    const base = document.title.replace(/^\(\d+\)\s*/, "");
    document.title = unreadCount > 0 ? `(${unreadCount}) ${base}` : base;
  }, [unreadCount, pathname]);

  const dismiss = useCallback(
    (key: string) => setToasts((prev) => prev.filter((t) => t.key !== key)),
    [],
  );

  const value = useMemo(
    () => ({ items, error, seenAt, unreadCount, markAllSeen }),
    [items, error, seenAt, unreadCount, markAllSeen],
  );

  return (
    <Ctx.Provider value={value}>
      {children}
      <ToastStack toasts={toasts} onDismiss={dismiss} />
    </Ctx.Provider>
  );
}

/** รวบเป็น toast เดียวเมื่อเข้ามาพร้อมกันหลายฉบับ — ห้ามปล่อยให้ toast ท่วมจอ */
function buildToasts(fresh: EmailIntakeActivityItem[]): Toast[] {
  const matched = fresh.filter((i) => i.outcome === "matched");
  const attention = fresh.filter((i) => INTAKE_OUTCOME[i.outcome].needsAction);
  const out: Toast[] = [];

  if (matched.length === 1) {
    const m = matched[0];
    out.push({
      key: m.id,
      title: "ใบสมัครใหม่ทางอีเมล",
      body: `${m.candidate_name ?? m.from_addr ?? "ผู้สมัคร"}${m.job_title ? ` · ${m.job_title}` : ""}`,
      href:
        m.job_id && m.candidate_id
          ? `/jobs/${m.job_id}/candidates/${m.candidate_id}`
          : "/intake",
      icon: "mark_email_unread",
      attention: false,
    });
  } else if (matched.length > 1) {
    out.push({
      key: `batch-${matched[0].id}`,
      title: `ใบสมัครใหม่ทางอีเมล ${matched.length} ฉบับ`,
      body: "เข้าคิววิเคราะห์ให้แล้ว",
      href: "/intake",
      icon: "mark_email_unread",
      attention: false,
    });
  }

  if (attention.length) {
    out.push({
      key: `attn-${attention[0].id}`,
      title:
        attention.length === 1
          ? "มีอีเมล 1 ฉบับที่รับเข้าระบบไม่ได้"
          : `มีอีเมล ${attention.length} ฉบับที่รับเข้าระบบไม่ได้`,
      body:
        attention.length === 1
          ? INTAKE_OUTCOME[attention[0].outcome].label
          : "เปิดดูว่าฉบับไหนต้องจัดการเอง",
      href: "/intake",
      icon: "mark_email_read",
      attention: true,
    });
  }
  return out;
}

function ToastStack({
  toasts,
  onDismiss,
}: {
  toasts: Toast[];
  onDismiss: (key: string) => void;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-4 right-4 left-4 sm:left-auto z-[60] flex flex-col gap-xs sm:w-96 pointer-events-none"
    >
      {toasts.map((t) => (
        <ToastItem key={t.key} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function ToastItem({
  toast,
  onDismiss,
}: {
  toast: Toast;
  onDismiss: (key: string) => void;
}) {
  const [paused, setPaused] = useState(false);

  // ปิดเองหลัง 8 วิ แต่หยุดนับเมื่อเอาเมาส์/โฟกัสไว้ — ให้เวลาอ่านชื่อคนจนจบ
  useEffect(() => {
    if (paused) return;
    const id = setTimeout(() => onDismiss(toast.key), TOAST_MS);
    return () => clearTimeout(id);
  }, [paused, toast.key, onDismiss]);

  return (
    <div
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
      className={`pointer-events-auto glass-card-elevated rounded-xl p-sm flex gap-sm items-start border-l-4 animate-toast-in ${
        toast.attention ? "border-l-tertiary" : "border-l-primary"
      }`}
    >
      <span
        className={`material-symbols-outlined text-[22px] flex-none ${
          toast.attention ? "text-tertiary" : "text-primary"
        }`}
        style={{ fontVariationSettings: "'FILL' 1" }}
        aria-hidden
      >
        {toast.icon}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-label-md font-semibold text-on-surface leading-snug">
          {toast.title}
        </p>
        <p className="text-label-sm text-on-surface-variant truncate">{toast.body}</p>
        <Link
          href={toast.href}
          onClick={() => onDismiss(toast.key)}
          className="inline-block mt-1 text-label-sm font-semibold text-primary hover:underline"
        >
          {toast.href === "/intake" ? "ดูรายการ" : "เปิดดูผู้สมัคร"} →
        </Link>
      </div>
      <button
        onClick={() => onDismiss(toast.key)}
        aria-label="ปิดการแจ้งเตือน"
        className="flex-none p-1 rounded-md text-outline hover:text-on-surface hover:bg-glass/40"
      >
        <span className="material-symbols-outlined text-[18px]">close</span>
      </button>
    </div>
  );
}
