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
    setBusy(true);
    setProgress(0);
    try {
      await uploadResumes(jobId, pdfs, setProgress);
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
    </div>
  );
}
