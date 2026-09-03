"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import AiInsight from "@/components/ai-insight";
import Breadcrumb from "@/components/breadcrumb";
import JDReviewCard from "@/components/jd-review-card";
import { createJob, reviewJD } from "@/lib/api";
import type { JDReview } from "@/lib/types";

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
  // state ของการ "ตรวจ" แยกจากการ "สร้าง" เด็ดขาด — คนละปุ่ม คนละผลลัพธ์
  const [reviewing, setReviewing] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [review, setReview] = useState<JDReview | null>(null);

  // แก้ข้อความแล้วผลตรวจเก่าใช้ไม่ได้อีก — ถ้าค้างไว้ HR จะเข้าใจว่าตรวจฉบับใหม่แล้ว
  function editText(next: string) {
    setRawText(next);
    if (review || reviewError) {
      setReview(null);
      setReviewError(null);
    }
  }

  async function handleReview() {
    if (!rawText.trim()) return;
    setReviewing(true);
    setReviewError(null);
    try {
      setReview(await reviewJD(rawText));
    } catch (e) {
      setReviewError(e instanceof Error ? e.message : "ตรวจ JD ไม่สำเร็จ");
    } finally {
      setReviewing(false);
    }
  }

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
          onChange={(e) => editText(e.target.value)}
          placeholder={PLACEHOLDER}
          rows={12}
          className="input-glass w-full resize-y"
        />
        {error && <p className="text-error text-label-md">{error}</p>}
        {reviewError && (
          <p className="text-error text-label-md" role="alert">
            {reviewError}
          </p>
        )}
        <div className="flex justify-end gap-xs flex-wrap">
          <button onClick={() => router.push("/")} className="btn-secondary-glass">
            ยกเลิก
          </button>
          {/* ปุ่มตรวจแยกจากปุ่มสร้างโดยตั้งใจ — ต้องกดเอง ไม่ยิงอัตโนมัติตอนพิมพ์
              เพราะแต่ละครั้งกินโควตา AI (ฟรีวันละ 20 ครั้ง) */}
          <button
            onClick={handleReview}
            disabled={reviewing || !rawText.trim()}
            className="btn-secondary-glass disabled:opacity-50"
          >
            <span className="material-symbols-outlined text-[18px]">rate_review</span>
            {reviewing ? "กำลังตรวจ JD…" : "ตรวจ JD ก่อนโพสต์"}
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

      {/* ผลตรวจเป็นคำแนะนำเท่านั้น — ปุ่ม "สร้างและวิเคราะห์" ด้านบนยังกดได้ตลอด
          ไม่ว่าจะเคยตรวจหรือไม่ และไม่ว่าผลตรวจจะบอกว่าอย่างไร */}
      {review && <JDReviewCard review={review} />}
    </div>
  );
}
