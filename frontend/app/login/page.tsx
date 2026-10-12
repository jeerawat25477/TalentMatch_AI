"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import ThemeToggle from "@/components/theme-toggle";
import { login } from "@/lib/api";

/**
 * หน้าเข้าสู่ระบบ — จอใหญ่แบ่งสองฝั่ง (แนะนำระบบ + ฟอร์ม) จอแคบเหลือเฉพาะฟอร์ม
 *
 * ปุ่มสลับธีมอยู่ที่นี่ด้วย เพราะค่าธีมถูกจำในเบราว์เซอร์เครื่องนั้น คนที่ยังไม่ได้ล็อกอิน
 * จึงไม่มีทางอื่นให้เปลี่ยน (หน้าตั้งค่าอยู่หลังประตู) — ใช้ปุ่มตัวเดียวกับในแอป ค่าที่เลือก
 * ติดไปหลังเข้าสู่ระบบ
 */

const POINTS = [
  { icon: "search_insights", text: "คัดกรองเรซูเม่พร้อมคะแนนที่บอกที่มาได้" },
  { icon: "view_kanban", text: "กระดานติดตามตั้งแต่นัดสัมภาษณ์จนรับเข้าทำงาน" },
  { icon: "how_to_reg", text: "ทุกคำตัดสินยังเป็นของ HR ระบบไม่ตัดสินแทน" },
];

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      router.replace("/");
    } catch (err) {
      // ข้อความ error จาก backend มาในรูป "<status>: <detail>" — โชว์เฉพาะ detail
      const msg = err instanceof Error ? err.message.replace(/^\d+:\s*/, "") : "เข้าสู่ระบบไม่สำเร็จ";
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    // pt เพิ่มบนจอเล็ก: ปุ่มธีมลอยมุมขวาบน จอ 320×640 การ์ดขึ้นไปทับมัน 12px
    <div className="relative min-h-screen flex items-center justify-center p-md pt-[4.5rem] sm:pt-md overflow-hidden">
      {/* แสงจาง ๆ หลังการ์ด — หน้านี้โล่งกว่าหน้าอื่น ถ้าไม่มีอะไรรองการ์ดกระจกจะดูลอยบนความว่าง
          ใช้สีของธีม (เปลี่ยนตามโหมดมืด/สว่างเอง) และ pointer-events-none กันไปบังการคลิก */}
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-32 -start-24 w-[28rem] h-[28rem] rounded-full bg-primary/20 blur-3xl" />
        <div className="absolute -bottom-40 -end-32 w-[32rem] h-[32rem] rounded-full bg-secondary/15 blur-3xl" />
      </div>

      <div className="absolute top-md end-md z-10">
        <ThemeToggle />
      </div>

      <div className="relative w-full max-w-4xl grid gap-lg lg:grid-cols-[1fr_22rem] items-center">
        {/* ฝั่งแนะนำระบบ — ซ่อนบนจอแคบ ไม่ให้ดันฟอร์มตกจอ */}
        <section className="hidden lg:block space-y-md">
          <div className="flex items-center gap-sm">
            <Logo />
            <div>
              <h1 className="text-headline-lg text-on-surface leading-tight">TalentMatch AI</h1>
              <p className="text-label-md text-on-surface-variant">ผู้ช่วยคัดกรองเรซูเม่สำหรับ HR</p>
            </div>
          </div>
          <p className="text-body-md text-on-surface-variant max-w-md leading-relaxed">
            อ่านเรซูเม่ทั้งกองแล้วเทียบกับเกณฑ์ของตำแหน่งให้ พร้อมบอกว่าแต่ละคะแนนมาจากอะไร
            เพื่อให้คุณตัดสินใจได้เร็วขึ้นโดยยังเห็นเหตุผลครบ
          </p>
          <ul className="space-y-sm">
            {POINTS.map((p) => (
              <li key={p.text} className="flex items-start gap-xs text-body-md text-on-surface">
                <span
                  className="material-symbols-outlined text-primary text-[20px] flex-none mt-0.5"
                  aria-hidden
                >
                  {p.icon}
                </span>
                {p.text}
              </li>
            ))}
          </ul>
        </section>

        <form
          onSubmit={submit}
          className="glass-card-elevated rounded-2xl p-lg w-full max-w-sm mx-auto space-y-md"
        >
          {/* บนจอแคบไม่มีฝั่งซ้าย จึงต้องมีโลโก้กับชื่อในฟอร์มด้วย */}
          <div className="lg:hidden text-center space-y-xs">
            <div className="flex justify-center">
              <Logo />
            </div>
            <h1 className="text-headline-md text-on-surface">TalentMatch AI</h1>
          </div>

          <div>
            <h2 className="text-headline-md text-on-surface">เข้าสู่ระบบ</h2>
            <p className="text-label-md text-on-surface-variant">
              ใช้ชื่อผู้ใช้และรหัสผ่านที่ผู้ดูแลระบบให้ไว้
            </p>
          </div>

          <label className="block space-y-xs">
            <span className="text-label-sm text-outline">ชื่อผู้ใช้</span>
            <span className="relative block">
              <span
                className="material-symbols-outlined absolute start-3 top-1/2 -translate-y-1/2 text-[20px] text-outline pointer-events-none"
                aria-hidden
              >
                person
              </span>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                // backend เทียบชื่อผู้ใช้แบบตัวพิมพ์ตรงทุกตัว — ไม่ปิด iPhone จะเปลี่ยน admin เป็น Admin ให้เอง
                // แล้วล็อกอินไม่ผ่านโดยขึ้นเหมือนรหัสผิด
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                autoFocus
                required
                disabled={busy}
                className="input-glass w-full ps-10"
              />
            </span>
          </label>

          <label className="block space-y-xs">
            <span className="text-label-sm text-outline">รหัสผ่าน</span>
            <span className="relative block">
              <span
                className="material-symbols-outlined absolute start-3 top-1/2 -translate-y-1/2 text-[20px] text-outline pointer-events-none"
                aria-hidden
              >
                lock
              </span>
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                disabled={busy}
                className="input-glass w-full ps-10 pe-11"
              />
              {/* ดู/ซ่อนรหัสผ่าน — แก้ที่พิมพ์ผิดได้โดยไม่ต้องลบทั้งช่อง */}
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "ซ่อนรหัสผ่าน" : "แสดงรหัสผ่าน"}
                title={showPassword ? "ซ่อนรหัสผ่าน" : "แสดงรหัสผ่าน"}
                className="absolute end-1.5 top-1/2 -translate-y-1/2 w-9 h-9 rounded-lg inline-flex items-center justify-center text-on-surface-variant hover:text-primary hover:bg-glass/40 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <span className="material-symbols-outlined text-[20px]">
                  {showPassword ? "visibility_off" : "visibility"}
                </span>
              </button>
            </span>
          </label>

          {error && (
            <p
              role="alert"
              className="flex gap-xs items-start p-sm rounded-xl border border-error/40 bg-error-container/20 text-label-md text-on-surface"
            >
              <span
                className="material-symbols-outlined text-error text-[18px] flex-none"
                style={{ fontVariationSettings: "'FILL' 1" }}
                aria-hidden
              >
                error
              </span>
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy || !username || !password}
            className="btn-primary w-full justify-center disabled:opacity-50"
          >
            <span
              className={`material-symbols-outlined text-[18px] ${busy ? "animate-spin" : ""}`}
              aria-hidden
            >
              {busy ? "progress_activity" : "login"}
            </span>
            {busy ? "กำลังเข้าสู่ระบบ…" : "เข้าสู่ระบบ"}
          </button>
        </form>
      </div>
    </div>
  );
}

function Logo() {
  return (
    <span
      aria-hidden
      className="w-14 h-14 flex-none rounded-2xl bg-gradient-to-br from-primary to-primary-container flex items-center justify-center text-on-primary shadow-lg shadow-primary/20"
    >
      <span className="material-symbols-outlined text-[30px]">person_search</span>
    </span>
  );
}
