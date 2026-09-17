import { BANDS, scoreBand } from "@/lib/types";

// วงแหวนคะแนน (conic-gradient) + ป้ายแบนด์ — ตาม mockup Candidate List
export default function ScoreRing({
  score,
  size = 56,
  showLabel = true,
}: {
  score: number | null;
  size?: number;
  /** false = วงอย่างเดียว สำหรับที่ที่ป้ายแบนด์ไม่มีความหมายแล้ว (เช่นกระดานติดตาม) */
  showLabel?: boolean;
}) {
  const band = BANDS[scoreBand(score)];
  const inner = size - 10;

  if (!showLabel) {
    return (
      <div
        title={score == null ? "ยังไม่มีคะแนน" : `คะแนนความเหมาะสม ${score}`}
        className="rounded-full flex-none flex items-center justify-center"
        style={{ width: size, height: size, background: band.ring }}
      >
        <div
          className="rounded-full bg-surface-container-lowest flex items-center justify-center font-bold"
          style={{ width: size - 10, height: size - 10, color: band.color, fontSize: 14 }}
        >
          {score == null ? "—" : score}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-base min-w-[84px]">
      <div
        className="rounded-full flex items-center justify-center"
        style={{ width: size, height: size, background: band.ring }}
      >
        <div
          className="rounded-full bg-surface-container-lowest flex items-center justify-center font-bold"
          style={{ width: inner, height: inner, color: band.color, fontSize: 14 }}
        >
          {score == null ? "—" : score}
        </div>
      </div>
      <div
        className="text-[10px] font-semibold tracking-wide uppercase text-center"
        style={{ color: band.color }}
      >
        {band.label}
      </div>
    </div>
  );
}
