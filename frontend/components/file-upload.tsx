"use client";

import { useRef, useState } from "react";
import { uploadResumes } from "@/lib/api";

// ช่องลากวางไฟล์ PDF หลายไฟล์ + progress bar
export default function FileUpload({
  jobId,
  onUploaded,
}: {
  jobId: string;
  onUploaded: () => void;
}) {
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  // ไฟล์ที่ backend ข้ามเพราะเคยอัปโหลดไปแล้ว — ต้องบอก HR ไม่งั้นจะงงว่าทำไมคนไม่ขึ้น
  const [duplicates, setDuplicates] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleFiles(fileList: FileList | null) {
    if (!fileList || fileList.length === 0) return;
    const pdfs = Array.from(fileList).filter((f) =>
      f.name.toLowerCase().endsWith(".pdf"),
    );
    if (pdfs.length === 0) {
      setError("รองรับเฉพาะไฟล์ PDF");
      return;
    }
    setError(null);
    setDuplicates([]);
    setBusy(true);
    setProgress(0);
    try {
      const result = await uploadResumes(jobId, pdfs, setProgress);
      setDuplicates(result.duplicate_files ?? []);
      onUploaded();
    } catch (e) {
      setError(e instanceof Error ? e.message : "อัปโหลดล้มเหลว");
    } finally {
      setBusy(false);
      setProgress(0);
    }
  }

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handleFiles(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        className={`cursor-pointer rounded-2xl border-2 border-dashed p-md text-center transition ${
          dragging
            ? "border-primary bg-primary/5"
            : "border-outline-variant bg-glass/40 hover:bg-glass/60"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          multiple
          hidden
          onChange={(e) => handleFiles(e.target.files)}
        />
        {busy ? (
          <div className="space-y-xs">
            <p className="text-label-md text-on-surface-variant">
              กำลังอัปโหลด… {progress}%
            </p>
            <div className="h-2 rounded-full bg-surface-container-high overflow-hidden max-w-sm mx-auto">
              <div
                className="h-full bg-primary rounded-full transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        ) : (
          <>
            <span className="material-symbols-outlined text-primary text-[32px]">
              cloud_upload
            </span>
            <p className="text-body-md text-on-surface">
              ลากไฟล์ Resume (PDF) มาวาง หรือคลิกเพื่อเลือก
            </p>
            <p className="text-label-sm text-outline mt-0.5">
              อัปโหลดพร้อมกันหลายไฟล์ได้
            </p>
          </>
        )}
      </div>
      {error && <p className="text-error text-label-md mt-xs">{error}</p>}
      {duplicates.length > 0 && (
        <div className="mt-xs p-sm rounded-xl border border-tertiary/30 bg-tertiary-container/10 flex gap-xs items-start">
          <span
            className="material-symbols-outlined text-tertiary text-[20px]"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            content_copy
          </span>
          {/* สีข้อความต้องเป็น on-surface ที่พลิกตามธีม — ตระกูล *-fixed ตั้งใจให้เหมือนกัน
              ทั้งสองธีม (น้ำตาลเข้ม) พอวางบนพื้นมืดแล้วอ่านไม่ออก */}
          <div>
            <p className="text-on-surface text-label-md leading-snug">
              ข้ามไฟล์ที่เคยอัปโหลดแล้ว {duplicates.length} ไฟล์
            </p>
            <p className="text-on-surface-variant text-label-sm leading-snug mt-0.5">
              {duplicates.join(", ")}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
