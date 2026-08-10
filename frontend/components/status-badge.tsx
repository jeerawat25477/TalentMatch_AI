import { BANDS, scoreBand } from "@/lib/types";

// ป้ายสถานะ — แบนด์ 50–70 (Needs Review) กะพริบเบา ๆ ตาม brief
export default function StatusBadge({ score }: { score: number | null }) {
  const key = scoreBand(score);
  const band = BANDS[key];
  return (
    <span
      className={`inline-block px-3 py-1 rounded-full text-label-sm font-bold whitespace-nowrap ${band.chip} ${
        key === "review" ? "animate-pulse-soft" : ""
      }`}
    >
      {band.label}
    </span>
  );
}
