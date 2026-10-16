"use client";

import {
  Briefcase,
  CalendarDays,
  History,
  Inbox,
  LogOut,
  Monitor,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Settings,
  Sun,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  DARK_QUERY,
  THEME_LABELS,
  THEME_STORAGE_KEY,
  applyTheme,
  nextTheme,
  readStoredTheme,
  type Theme,
} from "@/lib/theme";
import { useMe } from "@/lib/use-me";
import { useIntakeFeed } from "./intake-notifications";
import Tooltip from "./tooltip";

const LINKS = [
  { href: "/", icon: Briefcase, label: "ตำแหน่งงาน" },
  { href: "/interviews", icon: CalendarDays, label: "ตารางสัมภาษณ์" },
  { href: "/intake", icon: Inbox, label: "รับสมัครทางอีเมล", badge: true },
  { href: "/search", icon: Search, label: "ค้นหาผู้สมัคร" },
  { href: "/employees", icon: Users, label: "พนักงาน" },
];

// ผู้ดูแลเท่านั้น — บัญชีทดลองไม่เห็นเมนูนี้ (backend ตอบ 403 อยู่แล้ว)
const ADMIN_LINKS = [{ href: "/audit", icon: History, label: "ประวัติการใช้งาน", badge: false }];

const THEME_ICON: Record<Theme, typeof Sun> = {
  light: Sun,
  dark: Moon,
  system: Monitor,
};

// แถวเมนูมาตรฐาน — ไอคอนซ้าย ข้อความขวา · ตอนหุบ (collapsed) จัดไอคอนกลางและซ่อนข้อความ (เฉพาะ md+)
function rowClass(collapsed: boolean, active = false) {
  return [
    "flex items-center gap-sm px-sm py-xs rounded-lg transition-colors w-full",
    collapsed ? "md:justify-center md:px-0" : "",
    active
      ? "text-primary font-bold bg-primary/10"
      : "text-on-surface-variant hover:text-primary hover:bg-glass/20",
  ].join(" ");
}

// Collapsible Sidebar สไตล์ LangSmith
//   เดสก์ท็อป: กาง w-64 (ไอคอน+ข้อความ) ↔ หุบ w-16 (ไอคอนกลาง + tooltip)
//   มือถือ: เป็น drawer เลื่อนเข้า/ออก (ไม่ผูกกับ collapsed — โชว์เต็มเสมอ)
export default function SideNav({
  collapsed,
  onToggleCollapse,
  modKey,
  mobileOpen,
  onCloseMobile,
  username,
  onLogout,
}: {
  collapsed: boolean;
  onToggleCollapse: () => void;
  modKey: string;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  username: string | null;
  onLogout: () => void;
}) {
  const pathname = usePathname();
  const { unreadCount } = useIntakeFeed();
  const role = useMe().data?.role;
  const isDemo = role === "demo";
  const roleLabel = isDemo ? "บัญชีทดลอง" : role === "admin" ? "ผู้ดูแล" : "";
  const slide = mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0";
  const width = collapsed ? "md:w-16" : "md:w-64";
  // ข้อความจะถูกซ่อนเฉพาะตอนหุบและอยู่บนจอ md+ (มือถือ drawer โชว์ข้อความเสมอ)
  const labelHidden = collapsed ? "md:hidden" : "";

  // h-dvh ไม่ใช่ h-screen: บนมือถือ 100vh = ความสูงตอนแถบเบราว์เซอร์ซ่อน ส่วนล่าง (ออกจากระบบ)
  // จึงจมใต้แถบที่อยู่ จนกว่าจะเลื่อนหน้าให้แถบหด — หน้าสั้นเลื่อนไม่ได้เลยหาปุ่มไม่เจอ (2026-10-16)
  // overflow-y-auto เฉพาะมือถือ: จอแนวนอนเตี้ยกว่าเมนู ให้เลื่อนในเมนูได้ · ต้องคู่กับ overflow-x-hidden
  // (ตั้งแกนเดียว เบราว์เซอร์จะเปิดอีกแกนเป็น auto ให้เอง → ลากเมนูออกข้างได้ เจอบนมือถือจริง) · md ขึ้นไปต้อง visible
  // ไม่งั้น tooltip ตอนหุบ (โผล่ทางขวาของแถบ) โดนตัด
  return (
    <aside
      className={`fixed left-0 top-0 h-dvh w-64 ${width} ${slide}
        bg-glass/60 backdrop-blur-xl border-r border-glass/40 shadow-sm
        flex flex-col py-md px-sm z-50 transition-all duration-300 ease-in-out
        overflow-y-auto overflow-x-hidden md:overflow-visible`}
    >
      {/* ── บน: โลโก้ + ปุ่ม Toggle ── */}
      <div className={`flex items-center gap-xs ${collapsed ? "md:flex-col" : ""}`}>
        <Link
          href="/"
          aria-label="TalentMatch AI — หน้าแรก"
          className="flex items-center gap-xs min-w-0 rounded-lg
                     focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
        >
          <div className="w-10 h-10 flex-none rounded-xl bg-gradient-to-br from-primary to-primary-container flex items-center justify-center text-on-primary font-bold text-body-md">
            T
          </div>
          <div className={`min-w-0 ${labelHidden}`}>
            <h1 className="text-label-md font-bold text-primary leading-tight truncate">
              TalentMatch AI
            </h1>
            <p className="text-label-sm text-outline truncate">Recruitment Portal</p>
          </div>
        </Link>

        {/* ปุ่ม Toggle (เดสก์ท็อป) + Tooltip บอกคีย์ลัด */}
        <div className={collapsed ? "" : "md:ml-auto"}>
          <Tooltip
            label={`${collapsed ? "Expand" : "Collapse"} (${modKey}B)`}
          >
            <button
              onClick={onToggleCollapse}
              aria-label={collapsed ? "ขยายเมนู" : "หุบเมนู"}
              aria-expanded={!collapsed}
              className="hidden md:inline-flex p-2 rounded-lg text-on-surface-variant hover:bg-glass/40 hover:text-primary transition-colors
                         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              {collapsed ? (
                <PanelLeftOpen className="w-5 h-5" />
              ) : (
                <PanelLeftClose className="w-5 h-5" />
              )}
            </button>
          </Tooltip>
        </div>

        {/* ปิด drawer (มือถือ) */}
        <button
          onClick={onCloseMobile}
          aria-label="ปิดเมนู"
          className="md:hidden ml-auto p-1 rounded-lg text-on-surface-variant hover:bg-glass/40"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* ── กลาง: เมนูหลัก ── */}
      <nav className="flex-1 mt-xl space-y-1 overflow-y-auto overflow-x-hidden">
        {(role === "admin" ? [...LINKS, ...ADMIN_LINKS] : LINKS).map((l) => {
          const active =
            l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
          const Icon = l.icon;
          const count = l.badge ? unreadCount : 0;
          const countText = count > 99 ? "99+" : String(count);
          const tip = count ? `${l.label} (ใหม่ ${countText})` : l.label;
          return (
            <Tooltip key={l.href} label={tip} show={collapsed}>
              <Link
                href={l.href}
                aria-current={active ? "page" : undefined}
                aria-label={count ? `${l.label} — ใหม่ ${countText} รายการ` : undefined}
                className={rowClass(collapsed, active)}
              >
                <span className="relative flex-none">
                  <Icon className="w-5 h-5" strokeWidth={active ? 2.5 : 2} />
                  {/* ตอนหุบไม่มีที่ให้ตัวเลข — เหลือจุดบนไอคอนแทน */}
                  {count > 0 && collapsed && (
                    <span
                      aria-hidden
                      className="hidden md:block absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-primary ring-2 ring-surface"
                    />
                  )}
                </span>
                <span className={`text-body-md truncate ${labelHidden}`}>
                  {l.label}
                </span>
                {count > 0 && (
                  <span
                    aria-hidden
                    className={`ml-auto min-w-[1.5rem] h-6 px-1.5 rounded-full bg-primary text-on-primary text-label-sm font-bold flex items-center justify-center ${labelHidden}`}
                  >
                    {countText}
                  </span>
                )}
              </Link>
            </Tooltip>
          );
        })}
      </nav>

      {/* ── ล่างสุด: การตั้งค่า + โปรไฟล์ + ออกจากระบบ ── */}
      <div className="mt-auto pt-md border-t border-hairline space-y-1">
        <ThemeControl collapsed={collapsed} labelHidden={labelHidden} />

        <Tooltip label="การตั้งค่า" show={collapsed}>
          <Link
            href="/settings"
            aria-current={pathname.startsWith("/settings") ? "page" : undefined}
            className={rowClass(collapsed, pathname.startsWith("/settings"))}
          >
            <Settings className="w-5 h-5 flex-none" />
            <span className={`text-body-md truncate ${labelHidden}`}>
              การตั้งค่า
            </span>
          </Link>
        </Tooltip>

        {/* โปรไฟล์ + ระดับสิทธิ์ */}
        <Tooltip label={`${username ?? "ผู้ใช้"} · ${roleLabel}`} show={collapsed}>
          <div className={rowClass(collapsed).replace("hover:bg-glass/20", "")}>
            <div className="w-8 h-8 flex-none rounded-full bg-glass/70 border border-glass/50 flex items-center justify-center text-label-sm text-primary uppercase">
              {username ? username.slice(0, 2) : "HR"}
            </div>
            <div className={`min-w-0 ${labelHidden}`}>
              <p className="text-label-md text-on-surface truncate">
                {username ?? "ผู้ใช้"}
              </p>
              <p
                className={`text-label-sm truncate ${isDemo ? "text-tertiary font-semibold" : "text-outline"}`}
              >
                {roleLabel}
              </p>
            </div>
          </div>
        </Tooltip>

        {/* ออกจากระบบ */}
        <Tooltip label="ออกจากระบบ" show={collapsed}>
          <button
            onClick={onLogout}
            aria-label="ออกจากระบบ"
            className={`${rowClass(collapsed)} text-error hover:text-error hover:bg-error/5
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-error`}
          >
            <LogOut className="w-5 h-5 flex-none" />
            <span className={`text-body-md truncate ${labelHidden}`}>
              ออกจากระบบ
            </span>
          </button>
        </Tooltip>
      </div>
    </aside>
  );
}

// ปุ่มสลับธีม สว่าง → มืด → ตามระบบ (ตรรกะเดียวกับ lib/theme.ts)
// วนสถานะเมื่อคลิก · ตอนหุบใช้ Tooltip บอกสถานะปัจจุบัน
function ThemeControl({
  collapsed,
  labelHidden,
}: {
  collapsed: boolean;
  labelHidden: string;
}) {
  const [theme, setTheme] = useState<Theme>("system");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setTheme(readStoredTheme());
    setMounted(true);
  }, []);

  // โหมด "ตามระบบ" ต้องเปลี่ยนตามทันทีที่ OS สลับ
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia(DARK_QUERY);
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  function cycle() {
    const next = nextTheme(theme);
    setTheme(next);
    applyTheme(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* เขียนไม่ได้ก็ยังสลับได้ในหน้านี้ */
    }
  }

  const Icon = THEME_ICON[theme];
  const text = `ธีม: ${THEME_LABELS[theme]}`;

  return (
    <Tooltip label={text} show={collapsed}>
      <button
        onClick={cycle}
        aria-label={text}
        className={`${rowClass(collapsed)} focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary`}
      >
        {/* ก่อน mount ยังไม่รู้ธีมจริง — จาง ๆ กันไอคอนกระพริบผิด */}
        <Icon
          className="w-5 h-5 flex-none transition-opacity"
          style={{ opacity: mounted ? 1 : 0 }}
        />
        <span className={`text-body-md truncate ${labelHidden}`}>{text}</span>
      </button>
    </Tooltip>
  );
}
