"use client";

import Link from "next/link";

// เส้นทางนำทางมาตรฐาน — ทุกหน้าต้องมี เพื่อให้ตำแหน่งปัจจุบันชัดเจนเหมือนกันหมด
// รายการสุดท้ายคือหน้าปัจจุบันเสมอ (ไม่ต้องใส่ href)
export type Crumb = { label: string; href?: string };

export default function Breadcrumb({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="breadcrumb">
      <ol className="flex items-center gap-base text-outline text-label-sm flex-wrap">
        <li className="flex items-center gap-base">
          <Link
            href="/"
            aria-label="หน้าแรก"
            className="inline-flex items-center hover:text-primary transition-colors"
          >
            <span className="material-symbols-outlined text-[16px]">home</span>
          </Link>
        </li>

        {items.map((item, i) => {
          const isLast = i === items.length - 1;
          return (
            <li key={`${item.label}-${i}`} className="flex items-center gap-base">
              <span
                className="material-symbols-outlined text-[14px] text-outline/70"
                aria-hidden
              >
                chevron_right
              </span>
              {isLast || !item.href ? (
                <span
                  aria-current={isLast ? "page" : undefined}
                  className={
                    isLast
                      ? "text-primary font-semibold max-w-[240px] truncate"
                      : "max-w-[240px] truncate"
                  }
                  title={item.label}
                >
                  {item.label}
                </span>
              ) : (
                <Link
                  href={item.href}
                  className="hover:text-primary transition-colors max-w-[240px] truncate"
                  title={item.label}
                >
                  {item.label}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
