"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { SCREENING_PHOTOS_KEY, fetcher, getCandidatePhoto } from "@/lib/api";
import type { ScreeningPhotosSetting } from "@/lib/types";
import { initials } from "@/lib/types";

/**
 * สวิตช์ "แสดงรูปผู้สมัครหน้าคัดกรอง" — ใช้เฉพาะหน้าที่ HR ยังตัดสินผู้สมัครอยู่
 * ระหว่างโหลดหรือโหลดไม่ได้ถือว่าปิด (ฝั่งที่ปลอดภัย ไม่เผลอโชว์รูปก่อนรู้ค่าจริง)
 */
export function useScreeningPhotos(): boolean {
  const { data } = useSWR<ScreeningPhotosSetting>(SCREENING_PHOTOS_KEY, fetcher);
  return data?.enabled ?? false;
}

/**
 * วงรูปผู้สมัคร: มีรูปแสดงรูป ไม่มีรูป (404) หรือไม่ได้ขอให้แสดง → ตัวอักษรย่อแบบเดิม
 *
 * ขอรูปเมื่อกล่องเลื่อนมาใกล้จอเท่านั้น (IntersectionObserver) — รายชื่อยาว ๆ จะไม่ยิงขอรูป
 * ทุกใบพร้อมกัน และตัวอักษรย่อขึ้นก่อนเสมอ ไม่มีอะไรรอรูป
 * object URL ถูกคืนทุกครั้งที่ unmount หรือปิดสวิตช์ กันหน่วยความจำรั่ว
 */
export default function CandidateAvatar({
  candidateId,
  name,
  show,
  className = "",
  style,
}: {
  candidateId: string;
  name: string;
  /** false = ไม่ขอรูปเลย แสดงตัวอักษรย่อ */
  show: boolean;
  /** คลาสของกล่อง (ขนาด ความโค้ง สีตัวอักษร) — เหมือนกล่องตัวอักษรย่อเดิม */
  className?: string;
  /** สไตล์ของกล่องตอนเป็นตัวอักษรย่อ (เช่นสีพื้น) */
  style?: React.CSSProperties;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    setUrl(null);
    if (!show) return;
    let cancelled = false;
    let objectUrl: string | null = null;

    const load = () => {
      getCandidatePhoto(candidateId)
        .then((blob) => {
          if (cancelled || !blob) return;
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
        })
        .catch(() => {
          /* โหลดไม่ได้ก็ใช้ตัวอักษรย่อต่อไป — รูปเป็นของแถม */
        });
    };

    let io: IntersectionObserver | null = null;
    if (typeof IntersectionObserver === "undefined" || !ref.current) {
      load();
    } else {
      io = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) {
            io?.disconnect();
            load();
          }
        },
        { rootMargin: "200px" },
      );
      io.observe(ref.current);
    }

    return () => {
      cancelled = true;
      io?.disconnect();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [candidateId, show]);

  return (
    <div
      ref={ref}
      className={`overflow-hidden ${className}`}
      style={url ? undefined : style}
    >
      {url ? (
        // <img> ธรรมดา: blob URL ใช้กับ next/image ไม่ได้
        <img src={url} alt={`รูปของ ${name}`} className="w-full h-full object-cover" />
      ) : (
        initials(name)
      )}
    </div>
  );
}
