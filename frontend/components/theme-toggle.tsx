"use client";

import { useEffect, useState } from "react";
import {
  DARK_QUERY,
  THEME_ICONS,
  THEME_LABELS,
  THEME_STORAGE_KEY,
  applyTheme,
  nextTheme,
  readStoredTheme,
  type Theme,
} from "@/lib/theme";

export default function ThemeToggle() {
  // เริ่มที่ "system" เสมอเพื่อให้ HTML ฝั่ง server กับ client ตรงกัน
  // ค่าจริงอ่านใน useEffect (คลาส .dark ถูกตั้งไปแล้วโดยสคริปต์ใน layout)
  const [theme, setTheme] = useState<Theme>("system");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setTheme(readStoredTheme());
    setMounted(true);
  }, []);

  // โหมด "ตามระบบ" ต้องเปลี่ยนตามทันทีที่ OS สลับ โดยไม่ต้องรีเฟรช
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
      // เขียนไม่ได้ก็ยังสลับได้ในหน้านี้ แค่ไม่ถูกจำข้ามหน้า
    }
  }

  const label = THEME_LABELS[theme];

  return (
    <button
      onClick={cycle}
      // ก่อน mount ยังไม่รู้ธีมจริง — ซ่อนไอคอนไว้กัน label ผิดชั่วขณะ
      aria-label={`ธีม: ${label} (กดเพื่อเปลี่ยนเป็น ${THEME_LABELS[nextTheme(theme)]})`}
      title={`ธีม: ${label}`}
      className="p-2 rounded-lg text-on-surface-variant hover:bg-glass/40 hover:text-primary transition-colors
                 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
    >
      <span
        className="material-symbols-outlined"
        style={{ opacity: mounted ? 1 : 0 }}
      >
        {THEME_ICONS[theme]}
      </span>
    </button>
  );
}
