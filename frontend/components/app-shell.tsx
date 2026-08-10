"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getMe } from "@/lib/api";
import { clearToken, isAuthed } from "@/lib/auth";
import SideNav from "./side-nav";

const COLLAPSE_KEY = "tm-sidebar-collapsed";

// Sidebar-only layout: ไม่มี topbar — nav/โปรไฟล์/ธีม/logout อยู่ใน sidebar ทั้งหมด
// เดสก์ท็อป: หุบ/กางได้ (w-16 ↔ w-64) ด้วยปุ่ม toggle หรือ ⌘B/Ctrl+B
// มือถือ: sidebar เป็น drawer เปิดด้วยปุ่ม hamburger ลอย (ไม่เกี่ยวกับ collapse)
export default function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [modKey, setModKey] = useState("⌘"); // ปรับเป็น Ctrl บนที่ไม่ใช่ Mac หลัง mount
  const [username, setUsername] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);
  const pathname = usePathname();
  const router = useRouter();

  // หน้า login ไม่ต้องมี chrome/guard
  const isLoginPage = pathname === "/login";

  // guard: ไม่มี token → เด้งไป login (กันจอวาบด้วย state checking)
  useEffect(() => {
    if (isLoginPage) {
      setChecking(false);
      return;
    }
    if (!isAuthed()) {
      router.replace("/login");
      return;
    }
    // มี token — ยืนยันกับ backend ว่ายังใช้ได้ แล้วดึง username มาโชว์
    getMe()
      .then((u) => setUsername(u.username))
      .catch(() => {
        /* 401 จัดการใน api.ts (เด้ง login) แล้ว */
      })
      .finally(() => setChecking(false));
  }, [isLoginPage, pathname, router]);

  function logout() {
    clearToken();
    router.replace("/login");
  }

  // โหลดสถานะหุบ/กางที่จำไว้ + ตรวจว่าเป็น Mac ไหม (ไว้โชว์ ⌘ vs Ctrl)
  useEffect(() => {
    const saved = localStorage.getItem(COLLAPSE_KEY);
    if (saved !== null) setCollapsed(saved === "1");
    const platform = navigator.platform || navigator.userAgent;
    if (!/mac|iphone|ipad/i.test(platform)) setModKey("Ctrl+");
  }, []);
  useEffect(() => {
    localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
  }, [collapsed]);

  // คีย์ลัด ⌘B / Ctrl+B → สลับหุบ/กาง (เดสก์ท็อป)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        setCollapsed((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // เปลี่ยนหน้าแล้วปิด drawer บนมือถือ
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // ปิด drawer ด้วย Esc
  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMobileOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileOpen]);

  // หน้า login: แสดงเนื้อหาเปล่า ไม่มี sidebar
  if (isLoginPage) return <>{children}</>;

  // ระหว่างตรวจ token: อย่าเพิ่งวาดเนื้อหา (กันเห็นข้อมูลแวบก่อนเด้ง login)
  if (checking) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-outline text-label-md">กำลังตรวจสอบสิทธิ์…</p>
      </div>
    );
  }

  return (
    <>
      <SideNav
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((v) => !v)}
        modKey={modKey}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
        username={username}
        onLogout={logout}
      />

      {/* backdrop ของ drawer (มือถือ) */}
      {mobileOpen && (
        <div
          className="md:hidden fixed inset-0 bg-on-surface/30 backdrop-blur-sm z-40"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      )}

      {/* ปุ่มเปิดเมนูลอย (มือถือเท่านั้น) — แทนที่ hamburger ใน topbar ที่ถูกลบไป */}
      <button
        onClick={() => setMobileOpen(true)}
        aria-label="เปิดเมนู"
        className="md:hidden fixed top-3 left-3 z-30 p-2 rounded-lg bg-glass/70 backdrop-blur-md border border-glass/50 text-on-surface-variant hover:bg-glass shadow-sm transition-colors"
      >
        <span className="material-symbols-outlined">menu</span>
      </button>

      {/* Content ชิดขอบบน ไม่มี topbar · offset ตามความกว้าง sidebar (หุบ=16, กาง=64)
          เว้นบนบนมือถือให้พ้นปุ่มเมนูลอย */}
      <main
        className={`${
          collapsed ? "md:ml-16" : "md:ml-64"
        } p-sm md:p-lg pt-16 md:pt-lg min-h-screen relative transition-[margin] duration-300 ease-in-out`}
      >
        <div className="max-w-6xl mx-auto relative z-10">{children}</div>
      </main>
    </>
  );
}
