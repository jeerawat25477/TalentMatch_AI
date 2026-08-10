"use client";

import { Monitor, Moon, Palette, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import Breadcrumb from "@/components/breadcrumb";
import {
  DARK_QUERY,
  THEME_LABELS,
  THEME_STORAGE_KEY,
  applyTheme,
  readStoredTheme,
  type Theme,
} from "@/lib/theme";

const OPTIONS: { key: Theme; icon: typeof Sun; desc: string }[] = [
  { key: "light", icon: Sun, desc: "พื้นหลังสว่างตลอดเวลา" },
  { key: "dark", icon: Moon, desc: "พื้นหลังมืด ถนอมสายตาในที่แสงน้อย" },
  { key: "system", icon: Monitor, desc: "ปรับตามการตั้งค่าของเครื่อง" },
];

export default function SettingsPage() {
  const [theme, setTheme] = useState<Theme>("system");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setTheme(readStoredTheme());
    setMounted(true);
  }, []);

  // โหมด "ตามระบบ" ให้ตามทันทีที่ OS สลับ
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia(DARK_QUERY);
    const onChange = () => applyTheme("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  function choose(next: Theme) {
    setTheme(next);
    applyTheme(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* เขียนไม่ได้ก็ยังสลับได้ในหน้านี้ */
    }
  }

  return (
    <div className="max-w-2xl space-y-md">
      <Breadcrumb items={[{ label: "การตั้งค่า" }]} />

      <div>
        <p className="text-label-sm text-on-surface-variant uppercase tracking-wide">
          TalentMatch AI
        </p>
        <h1 className="text-headline-lg text-on-surface">การตั้งค่า</h1>
      </div>

      {/* หน้าตา / ธีม */}
      <section className="glass-card rounded-2xl p-md space-y-sm">
        <div className="flex items-center gap-xs text-on-surface">
          <Palette className="w-5 h-5 text-primary" />
          <h2 className="text-headline-md">หน้าตา</h2>
        </div>
        <p className="text-body-md text-on-surface-variant">
          เลือกธีมของทั้งเว็บ ระบบจะจำค่าไว้ในเบราว์เซอร์นี้
        </p>

        <div className="grid gap-sm sm:grid-cols-3">
          {OPTIONS.map((o) => {
            const active = mounted && theme === o.key;
            const Icon = o.icon;
            return (
              <button
                key={o.key}
                onClick={() => choose(o.key)}
                aria-pressed={active}
                className={`text-left p-md rounded-xl border transition-all ${
                  active
                    ? "border-primary bg-primary/10 shadow-md shadow-primary/20"
                    : "border-outline/30 hover:border-primary/50 hover:bg-glass/30"
                }`}
              >
                <Icon
                  className={`w-6 h-6 mb-xs ${active ? "text-primary" : "text-on-surface-variant"}`}
                />
                <p className="text-label-md font-semibold text-on-surface">
                  {THEME_LABELS[o.key]}
                </p>
                <p className="text-label-sm text-outline mt-0.5">{o.desc}</p>
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}
