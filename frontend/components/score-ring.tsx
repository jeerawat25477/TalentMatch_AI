import { BANDS, scoreBand } from "@/lib/types";

// วงแหวนคะแนน (conic-gradient) + ป้ายแบนด์ — ตาม mockup Candidate List
export default function ScoreRing({
  score,
  size = 56,
}: {
  score: number | null;
  size?: number;
}) {
  const band = BANDS[scoreBand(score)];
  const inner = size - 10;

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
