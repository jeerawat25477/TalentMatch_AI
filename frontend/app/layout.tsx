import type { Metadata } from "next";
import { Inter, Sarabun } from "next/font/google";
import "./globals.css";
import AppShell from "@/components/app-shell";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const sarabun = Sarabun({
  subsets: ["thai", "latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-sarabun",
});

export const metadata: Metadata = {
  title: "TalentMatch AI",
  description: "ผู้ช่วย HR คัดกรอง resume ด้วย AI multi-agent",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // suppressHydrationWarning: สคริปต์ด้านล่างเติมคลาส .dark ก่อน React hydrate
    <html lang="th" suppressHydrationWarning>
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
          rel="stylesheet"
        />
        {/* ต้องรันแบบ blocking ก่อนเบราว์เซอร์วาดเฟรมแรก ไม่งั้นผู้ใช้โหมดมืดจะเห็นจอขาวแวบ (FOUC)
            คีย์/ค่าต้องตรงกับ lib/theme.ts */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem("tm-theme");if(t!=="light"&&t!=="dark"&&t!=="system")t="system";if(t==="dark"||(t==="system"&&matchMedia("(prefers-color-scheme: dark)").matches))document.documentElement.classList.add("dark")}catch(e){}`,
          }}
        />
      </head>
      <body className={`${inter.variable} ${sarabun.variable} font-sans`}>
        {/* ก้อนแสงเบลอด้านหลัง — ให้ glass มีสีให้ดูดขึ้นมา
            ต้องครอบด้วยกล่อง fixed+overflow-hidden ไม่งั้นก้อนที่ยื่นออกนอกจอ
            จะทำให้หน้าเลื่อนแนวนอนได้บนจอแคบ (body{overflow-x:hidden} ไม่คลิป element แบบ fixed) */}
        <div
          aria-hidden
          className="pointer-events-none fixed inset-0 overflow-hidden -z-10"
        >
          <div
            className="absolute -top-44 -right-40 w-[520px] h-[520px] rounded-full blur-[10px]"
            style={{
              background: "radial-gradient(circle, var(--blob-a), transparent 70%)",
            }}
          />
          <div
            className="absolute -bottom-52 -left-36 w-[480px] h-[480px] rounded-full blur-[10px]"
            style={{
              background: "radial-gradient(circle, var(--blob-b), transparent 70%)",
            }}
          />
        </div>

        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
