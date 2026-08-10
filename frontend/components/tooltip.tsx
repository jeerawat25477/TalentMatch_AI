"use client";

// Tooltip แบบ CSS-only (ไม่พึ่ง lib) — โผล่ทางขวาของ trigger ให้เหมาะกับ sidebar
// ใช้โทเคน inverse-surface จึงคอนทราสต์กลับด้านอัตโนมัติทั้งธีมสว่าง/มืด
// show=false → คืน children เฉย ๆ (เช่น ตอน sidebar กางอยู่ไม่ต้องมี tooltip ชื่อเมนู)
export default function Tooltip({
  label,
  show = true,
  className = "",
  children,
}: {
  label: string;
  show?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  if (!show) return <>{children}</>;

  return (
    <span className={`group/tt relative flex ${className}`}>
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute left-full top-1/2 z-50 ml-2 -translate-y-1/2 -translate-x-1
                   whitespace-nowrap rounded-md bg-inverse-surface px-2 py-1 text-label-sm text-inverse-on-surface
                   opacity-0 shadow-lg transition-all duration-150
                   group-hover/tt:translate-x-0 group-hover/tt:opacity-100
                   group-focus-within/tt:translate-x-0 group-focus-within/tt:opacity-100"
      >
        {label}
      </span>
    </span>
  );
}
