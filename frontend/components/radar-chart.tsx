import type { GapAnalysis } from "@/lib/types";

// สองซีรีส์: Job Specs (สิ่งที่ตำแหน่งต้องการ) vs Candidate (สิ่งที่ผู้สมัครมี)
// สีผ่านการตรวจ CVD แล้ว (ΔE 27 protan / 31 normal) และมี legend + ป้ายแกนกำกับเสมอ
// ค่าจริงอยู่ใน globals.css — โหมดมืดต้องสลับเป็นคู่สว่าง (น้ำเงินอ่อน/ส้มอ่อน) ไม่งั้นเส้นจมพื้น
const JOB_COLOR = "var(--chart-job)";
const JOB_FILL = "var(--chart-job-fill)";
const CAND_COLOR = "var(--chart-cand)";
const CAND_FILL = "var(--chart-cand-fill)";
const GRID_COLOR = "var(--chart-grid)";

const MAX_AXES = 8;
const SIZE = 200;
const C = SIZE / 2;
const R = 80;

type Axis = { label: string; job: number; candidate: number };

function buildAxes(gap: GapAnalysis): Axis[] {
  // required = ความต้องการเต็ม (1.0), preferred = อยากได้ (0.7)
  const required = [...gap.matched_required, ...gap.missing_required].map((s) => ({
    label: s,
    job: 1,
    candidate: gap.matched_required.includes(s) ? 1 : 0,
  }));
  const preferred = [...gap.matched_preferred, ...gap.missing_preferred].map((s) => ({
    label: s,
    job: 0.7,
    candidate: gap.matched_preferred.includes(s) ? 0.7 : 0,
  }));
  return [...required, ...preferred].slice(0, MAX_AXES);
}

function pointAt(index: number, total: number, value: number) {
  const angle = (-90 + (index * 360) / total) * (Math.PI / 180);
  return {
    x: C + R * value * Math.cos(angle),
    y: C + R * value * Math.sin(angle),
  };
}

export default function RadarChart({ gap }: { gap: GapAnalysis | null }) {
  if (!gap) return null;
  const axes = buildAxes(gap);
  if (axes.length < 3) return null; // แกนน้อยกว่า 3 วาดเรดาร์ไม่ได้ (ใช้รายการทักษะด้านล่างแทน)

  const n = axes.length;
  const poly = (key: "job" | "candidate") =>
    axes
      .map((a, i) => {
        const p = pointAt(i, n, a[key]);
        return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
      })
      .join(" ");

  return (
    <div>
      {/* Legend — ต้องมีเสมอเมื่อมี 2 ซีรีส์ */}
      <div className="flex gap-sm justify-end mb-xs">
        <LegendItem color={JOB_COLOR} label="ตำแหน่งต้องการ" />
        <LegendItem color={CAND_COLOR} label="ผู้สมัครมี" />
      </div>

      <div className="relative flex items-center justify-center py-md">
        <svg
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          className="w-full max-w-[300px] drop-shadow-sm overflow-visible"
          role="img"
          aria-label="กราฟเรดาร์เปรียบเทียบทักษะที่ตำแหน่งต้องการกับทักษะที่ผู้สมัครมี"
        >
          {/* วงกริดพื้นหลัง */}
          {[20, 40, 60, 80].map((r) => (
            <circle
              key={r}
              cx={C}
              cy={C}
              r={r}
              fill="none"
              stroke={GRID_COLOR}
              strokeWidth={1}
            />
          ))}
          {/* เส้นแกน */}
          {axes.map((_, i) => {
            const p = pointAt(i, n, 1);
            return (
              <line
                key={i}
                x1={C}
                y1={C}
                x2={p.x}
                y2={p.y}
                stroke={GRID_COLOR}
                strokeWidth={1}
              />
            );
          })}

          {/* Job spec */}
          <polygon
            points={poly("job")}
            fill={JOB_FILL}
            stroke={JOB_COLOR}
            strokeWidth={2}
          />
          {/* Candidate */}
          <polygon
            points={poly("candidate")}
            fill={CAND_FILL}
            stroke={CAND_COLOR}
            strokeWidth={2}
          />

          {/* จุดของผู้สมัคร + tooltip ต่อแกน */}
          {axes.map((a, i) => {
            const p = pointAt(i, n, a.candidate);
            return (
              <circle key={a.label} cx={p.x} cy={p.y} r={4} fill={CAND_COLOR}>
                <title>
                  {a.label}: {a.candidate > 0 ? "มีทักษะนี้" : "ยังไม่มีทักษะนี้"}
                </title>
              </circle>
            );
          })}

          {/* ป้ายชื่อแกน */}
          {axes.map((a, i) => {
            const p = pointAt(i, n, 1.22);
            return (
              <text
                key={a.label}
                x={p.x}
                y={p.y}
                textAnchor="middle"
                dominantBaseline="middle"
                className="fill-outline"
                style={{ fontSize: 9, fontWeight: 600 }}
              >
                {a.label.length > 14 ? `${a.label.slice(0, 13)}…` : a.label}
              </text>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

function LegendItem({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-xs">
      <span
        className="w-3 h-3 rounded-full inline-block"
        style={{ background: color }}
      />
      <span className="text-label-sm text-outline">{label}</span>
    </div>
  );
}
