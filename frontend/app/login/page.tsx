"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { login } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
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
    <div className="min-h-screen flex items-center justify-center p-md">
      <form
        onSubmit={submit}
        className="glass-card-elevated rounded-2xl p-lg w-full max-w-sm space-y-md"
      >
        <div className="text-center space-y-xs">
          <div className="w-14 h-14 mx-auto rounded-2xl bg-gradient-to-br from-primary to-primary-container flex items-center justify-center text-on-primary font-bold text-headline-md">
            T
          </div>
          <h1 className="text-headline-md text-on-surface">TalentMatch AI</h1>
          <p className="text-label-md text-on-surface-variant">เข้าสู่ระบบเพื่อใช้งาน</p>
        </div>

        <label className="block text-label-sm text-outline">
          ชื่อผู้ใช้
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
            className="input-glass w-full mt-0.5"
          />
        </label>

        <label className="block text-label-sm text-outline">
          รหัสผ่าน
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            className="input-glass w-full mt-0.5"
          />
        </label>

        {error && (
          <p className="text-error text-label-md" role="alert">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy || !username || !password}
          className="btn-primary w-full disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-[18px]">login</span>
          {busy ? "กำลังเข้าสู่ระบบ…" : "เข้าสู่ระบบ"}
        </button>
      </form>
    </div>
  );
}
