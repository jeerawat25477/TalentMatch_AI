"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import AiInsight from "@/components/ai-insight";
import Breadcrumb from "@/components/breadcrumb";
import { createJob } from "@/lib/api";

const PLACEHOLDER = `ตำแหน่ง: Senior Python Developer
ประสบการณ์ขั้นต่ำ: 3 ปี
ทักษะที่ต้องมี: Python, FastAPI, PostgreSQL
ทักษะที่มีก็ดี: Docker, LangGraph
การศึกษา: ปริญญาตรีสาขาคอมพิวเตอร์`;

export default function NewJobPage() {
  const router = useRouter();
  const [rawText, setRawText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!rawText.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const job = await createJob(rawText);
      router.push(`/jobs/${job.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "สร้างงานไม่สำเร็จ");
      setBusy(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-md">
      <Breadcrumb
        items={[
          { label: "ตำแหน่งงาน", href: "/" },
          { label: "สร้างตำแหน่งใหม่" },
        ]}
      />

      <div>
        <h1 className="text-headline-lg text-on-surface">สร้างตำแหน่งงานใหม่</h1>
        <p className="text-body-md text-on-surface-variant">
          วางข้อความ Job Description แล้ว AI จะสกัดทักษะที่ต้องการให้อัตโนมัติ
        </p>
      </div>

      <AiInsight title="ทำงานอย่างไร">
        ระบบจะส่ง JD ให้ตัววิเคราะห์แยกเป็น ทักษะที่ต้องมี / ทักษะที่อยากได้ /
        ประสบการณ์ขั้นต่ำ แล้วใช้เกณฑ์นี้ให้คะแนนผู้สมัครทุกคนที่อัปโหลดเข้ามา
      </AiInsight>

      <div className="glass-card-elevated rounded-2xl p-md space-y-sm">
        <textarea
          value={rawText}
          onChange={(e) => setRawText(e.target.value)}
          placeholder={PLACEHOLDER}
          rows={12}
          className="input-glass w-full resize-y"
        />
        {error && <p className="text-error text-label-md">{error}</p>}
        <div className="flex justify-end gap-xs">
          <button onClick={() => router.push("/")} className="btn-secondary-glass">
            ยกเลิก
          </button>
          <button
            onClick={handleSubmit}
            disabled={busy || !rawText.trim()}
            className="btn-primary"
          >
            {busy ? (
              "กำลังวิเคราะห์ JD…"
            ) : (
              <>
                <span className="material-symbols-outlined text-[18px]">
                  auto_awesome
                </span>
                สร้างและวิเคราะห์
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
