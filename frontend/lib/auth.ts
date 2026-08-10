// จัดการ token ฝั่ง client — เก็บใน localStorage
// หมายเหตุความปลอดภัย: localStorage โดน XSS ได้ (httpOnly cookie ปลอดภัยกว่า แต่ cross-origin
// 4000→8000 ต้อง SameSite=None+Secure ยุ่งกว่าใน dev) — เลือก Bearer token ตามแพตเทิร์น SPA
// ดู tradeoff ใน memory-bank/04_security.md

const TOKEN_KEY = "tm-token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null; // ระวัง SSR
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function isAuthed(): boolean {
  return getToken() !== null;
}
