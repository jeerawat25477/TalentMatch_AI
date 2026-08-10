// ตรรกะธีมที่ใช้ร่วมกันระหว่างสคริปต์กัน FOUC ใน layout กับปุ่มสลับธีม
// คีย์และค่าต้องตรงกับสคริปต์ inline ใน app/layout.tsx เป๊ะ ๆ

export type Theme = "light" | "dark" | "system";

export const THEME_STORAGE_KEY = "tm-theme";

export const DARK_QUERY = "(prefers-color-scheme: dark)";

export const THEME_LABELS: Record<Theme, string> = {
  light: "สว่าง",
  dark: "มืด",
  system: "ตามระบบ",
};

export const THEME_ICONS: Record<Theme, string> = {
  light: "light_mode",
  dark: "dark_mode",
  system: "contrast",
};

export function isTheme(value: unknown): value is Theme {
  return value === "light" || value === "dark" || value === "system";
}

export function readStoredTheme(): Theme {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(saved) ? saved : "system";
  } catch {
    return "system"; // localStorage ถูกบล็อก (โหมดส่วนตัวบางเบราว์เซอร์)
  }
}

/** เขียนคลาส .dark ลง <html> — จุดเดียวที่ตัดสินว่าหน้าจอมืดหรือสว่าง */
export function applyTheme(theme: Theme) {
  const dark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia(DARK_QUERY).matches);
  document.documentElement.classList.toggle("dark", dark);
}

/** วนสถานะปุ่ม: สว่าง → มืด → ตามระบบ → สว่าง */
export function nextTheme(theme: Theme): Theme {
  if (theme === "light") return "dark";
  if (theme === "dark") return "system";
  return "light";
}
