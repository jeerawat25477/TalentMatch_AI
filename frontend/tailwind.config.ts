import type { Config } from "tailwindcss";

// โทเคนทั้งหมดพอร์ตมาจาก DESIGN.md ("Luminous HR") — อย่า hardcode สีนอกชุดนี้
//
// ทุกสีชี้ไปที่ CSS variable ที่ประกาศไว้ใน globals.css (:root = light, .dark = dark)
// ค่าใน var เก็บเป็น "R G B" ล้วน ไม่ใช่ hex — จำเป็นเพื่อให้ opacity modifier
// (เช่น bg-glass/60, border-outline/80) ยังคำนวณได้ผ่าน <alpha-value>
const c = (name: string) => `rgb(var(--c-${name}) / <alpha-value>)`;

const config: Config = {
  // สลับธีมด้วยคลาส .dark บน <html> (ตั้งโดยสคริปต์ใน layout.tsx ก่อน paint)
  darkMode: "class",
  // ต้องรวม lib/ ด้วย — BANDS ใน lib/types.ts ถือคลาสสีของ badge ไว้
  // ถ้าไม่ scan Tailwind จะไม่ generate คลาสพวกนั้น (ป้ายจะไม่มีพื้นหลัง)
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        surface: c("surface"),
        "surface-dim": c("surface-dim"),
        "surface-bright": c("surface-bright"),
        "surface-container-lowest": c("surface-container-lowest"),
        "surface-container-low": c("surface-container-low"),
        "surface-container": c("surface-container"),
        "surface-container-high": c("surface-container-high"),
        "surface-container-highest": c("surface-container-highest"),
        "surface-variant": c("surface-variant"),
        "surface-tint": c("surface-tint"),
        "on-surface": c("on-surface"),
        "on-surface-variant": c("on-surface-variant"),
        "inverse-surface": c("inverse-surface"),
        "inverse-on-surface": c("inverse-on-surface"),
        outline: c("outline"),
        "outline-variant": c("outline-variant"),

        primary: c("primary"),
        "on-primary": c("on-primary"),
        "primary-container": c("primary-container"),
        "on-primary-container": c("on-primary-container"),
        "inverse-primary": c("inverse-primary"),
        "primary-fixed": c("primary-fixed"),
        "primary-fixed-dim": c("primary-fixed-dim"),
        "on-primary-fixed": c("on-primary-fixed"),
        "on-primary-fixed-variant": c("on-primary-fixed-variant"),

        secondary: c("secondary"),
        "on-secondary": c("on-secondary"),
        "secondary-container": c("secondary-container"),
        "on-secondary-container": c("on-secondary-container"),
        "secondary-fixed": c("secondary-fixed"),
        "secondary-fixed-dim": c("secondary-fixed-dim"),
        "on-secondary-fixed": c("on-secondary-fixed"),
        "on-secondary-fixed-variant": c("on-secondary-fixed-variant"),

        tertiary: c("tertiary"),
        "on-tertiary": c("on-tertiary"),
        "tertiary-container": c("tertiary-container"),
        "on-tertiary-container": c("on-tertiary-container"),
        "tertiary-fixed": c("tertiary-fixed"),
        "tertiary-fixed-dim": c("tertiary-fixed-dim"),
        "on-tertiary-fixed": c("on-tertiary-fixed"),
        "on-tertiary-fixed-variant": c("on-tertiary-fixed-variant"),

        error: c("error"),
        "on-error": c("on-error"),
        "error-container": c("error-container"),
        "on-error-container": c("on-error-container"),

        background: c("background"),
        "on-background": c("on-background"),

        // พื้นผิวกระจก — โหมดสว่างคือขาว, โหมดมืดคือ navy อ่อน
        // ใช้แทน bg-white/xx เดิม ที่สลับธีมไม่ได้
        glass: c("glass"),
        // เส้นคั่นจางในการ์ด (เดิมคือ border-black/5)
        hairline: c("hairline"),
      },
      spacing: {
        base: "4px",
        xs: "8px",
        sm: "16px",
        md: "24px",
        lg: "40px",
        xl: "64px",
        gutter: "24px",
        "margin-mobile": "16px",
        "margin-desktop": "48px",
      },
      borderRadius: {
        // การ์ด/คอนเทนเนอร์หลัก = 2xl (1.5rem) ตาม DESIGN.md; ปุ่ม/อินพุตใช้ lg (0.5rem) ค่าเริ่มต้น
        "2xl": "1.5rem",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "var(--font-sarabun)", "system-ui", "sans-serif"],
      },
      fontSize: {
        "headline-xl": ["48px", { lineHeight: "56px", letterSpacing: "-0.02em", fontWeight: "700" }],
        "headline-lg": ["32px", { lineHeight: "40px", letterSpacing: "-0.01em", fontWeight: "600" }],
        "headline-md": ["24px", { lineHeight: "32px", fontWeight: "600" }],
        "body-lg": ["18px", { lineHeight: "28px", fontWeight: "400" }],
        "body-md": ["16px", { lineHeight: "24px", fontWeight: "400" }],
        "label-md": ["14px", { lineHeight: "20px", letterSpacing: "0.01em", fontWeight: "500" }],
        "label-sm": ["12px", { lineHeight: "16px", fontWeight: "600" }],
      },
    },
  },
  plugins: [],
};

export default config;
