import type { FunnelStage } from "@/lib/types";

// กรวยผู้สมัครรวมทั้งตำแหน่ง — แท่งแนวนอนลดหลั่นตามสัดส่วนของขั้นแรก
// backend การันตีว่าเป็นเซตซ้อนกัน (ขั้นหลัง ≤ ขั้นก่อนเสมอ) จึงคิด % เทียบขั้นแรกได้ตรง ๆ
// ไม่มี chart library ในโปรเจกต์นี้ และไม่ต้องมี — แท่งคือ div ที่กำหนดความกว้างเป็น %
export default function PipelineFunnel({ stages }: { stages: FunnelStage[] }) {
  const total = stages[0]?.count ?? 0;

  return (
    <div className="glass-card rounded-2xl p-md">
      <p className="text-label-md font-semibold text-on-surface mb-0.5">
        ผู้สมัครไปถึงขั้นไหนแล้ว
      </p>
      <p className="text-label-sm text-on-surface-variant mb-sm">
        นับสะสม — คนที่อยู่ขั้นล่างถูกนับในขั้นบนด้วย
      </p>

      {total === 0 ? (
        <p className="text-label-md text-outline">ยังไม่มีผู้สมัครในตำแหน่งนี้</p>
      ) : (
        <div className="flex flex-col gap-base">
          {stages.map((s, i) => {
            const pct = Math.round((s.count / total) * 100);
            return (
              <div key={s.label} className="flex items-center gap-sm">
                <span className="w-[130px] flex-none text-label-sm text-on-surface-variant">
                  {s.label}
                </span>
                {/* รางเต็มความกว้างเสมอ แท่งข้างในยาวตามสัดส่วน — ตาเทียบขั้นต่อขั้นได้ */}
                <div className="flex-1 h-7 rounded-lg bg-glass/50 border border-outline/20 overflow-hidden">
                  <div
                    className="h-full rounded-lg bg-primary/80"
                    // ความกว้างเป็นค่าที่คำนวณจากข้อมูล ไม่ใช่สี จึงใช้ style ได้ตามปกติ
                    // (ขั้นต่ำ 2% เพื่อให้ขั้นที่มี 1 คนยังเห็นเป็นแท่ง ไม่ใช่เส้นหาย)
                    style={{ width: `${Math.max(pct, s.count > 0 ? 2 : 0)}%` }}
                  />
                </div>
                <span className="w-[86px] flex-none text-right text-label-md text-on-surface">
                  <b>{s.count}</b>{" "}
                  <span className="text-on-surface-variant">
                    {i === 0 ? "คน" : `(${pct}%)`}
                  </span>
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
