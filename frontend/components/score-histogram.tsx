import type { ScoreDistribution } from "@/lib/types";

/**
 * ฮิสโตแกรมกระจายคะแนนของผู้สมัครทั้งตำแหน่ง — ใช้สองที่ด้วย component เดียว
 * หน้าภาพรวมตำแหน่งงาน (ไม่ปักหมุด) และหน้ารายละเอียดผู้สมัคร (ปักหมุดคะแนนของคนนี้)
 *
 * เส้นแบ่งแบนด์วาดจาก `auto_advance_above` / `review_from` ที่ backend ส่งมาจาก bands.py
 * **ไม่เขียนเลข 50/70 ที่นี่** — เส้นและพื้นสามโซนใช้สี --band-* ซึ่งสงวนไว้สำหรับแบนด์คะแนน
 * พอดี (นี่คือการแสดงแบนด์จริง ไม่ใช่ของตกแต่ง)
 *
 * ความสูงแท่งเทียบกับแท่งที่สูงที่สุด ไม่ใช่เทียบกับจำนวนทั้งหมด — สัดส่วนระหว่างแท่งเท่ากัน
 * ทุกประการ แต่ถ้าเทียบจำนวนทั้งหมด คะแนนที่กระจายกว้างจะได้แท่งเตี้ยจนอ่านไม่ออก
 * ตัวเลขจำนวนคนอยู่บนหัวแท่งเสมอ จึงไม่ต้องเดาจากความสูง
 *
 * div ล้วน ไม่มี chart library เหมือน pipeline-funnel
 *
 * `children` วางต่อท้ายในการ์ดเดียวกัน — หน้าภาพรวมตำแหน่งใช้ใส่ "ดูทักษะที่ขาดบ่อย" แบบพับได้
 */
export default function ScoreHistogram({
  data,
  highlightScore,
  compact = false,
  children,
}: {
  data: ScoreDistribution;
  /** คะแนนของผู้สมัครคนที่กำลังดู — ไม่ส่ง = ไม่ปักหมุด */
  highlightScore?: number | null;
  /** เตี้ยลงสำหรับหน้าที่กราฟนี้เป็นข้อมูลประกอบ (หน้ารายละเอียดผู้สมัคร) ไม่ใช่พระเอกของหน้า */
  compact?: boolean;
  /** ส่วนเสริมท้ายการ์ด (เช่นทักษะที่ขาดบ่อยแบบพับได้) */
  children?: React.ReactNode;
}) {
  const { buckets, total } = data;
  const step = buckets.length > 1 ? buckets[1].range_start - buckets[0].range_start : 10;
  const top = buckets.length ? buckets[buckets.length - 1].range_start + step : 100;
  const max = Math.max(0, ...buckets.map((b) => b.count));
  const pct = (v: number) => (Math.min(Math.max(v, 0), top) / top) * 100;
  const hasPin = highlightScore != null;
  const pinBucket = hasPin
    ? Math.min(Math.floor((highlightScore as number) / step), buckets.length - 1)
    : -1;

  // สามโซนตามแบนด์ — พื้นจาง ๆ บอกว่าแท่งไหนตกอยู่ในแบนด์ไหน โดยไม่ต้องอ่านคำอธิบายเส้น
  const zones = [
    { from: 0, to: data.review_from, color: "var(--band-fail)", label: "ไม่ผ่าน" },
    { from: data.review_from, to: data.auto_advance_above, color: "var(--band-review)", label: "รอ HR" },
    { from: data.auto_advance_above, to: top, color: "var(--band-pass)", label: "ผ่านอัตโนมัติ" },
  ];
  const lines = [
    { at: data.review_from, color: "var(--band-review)" },
    { at: data.auto_advance_above, color: "var(--band-pass)" },
  ];
  const tint = (color: string, amount: number) =>
    `color-mix(in srgb, ${color} ${amount}%, transparent)`;

  return (
    <div className="glass-card rounded-2xl p-md">
      <p className="text-label-md font-semibold text-on-surface mb-0.5">การกระจายคะแนน</p>
      <p className="text-label-sm text-on-surface-variant mb-sm">
        {total > 0
          ? `ผู้สมัครที่มีผลคะแนนแล้ว ${total} คน ในตำแหน่งนี้`
          : "นับเฉพาะผู้สมัครที่มีผลคะแนนแล้ว"}
      </p>

      {total === 0 ? (
        <p className="text-label-md text-outline">ยังไม่มีผู้สมัครที่มีผลคะแนน</p>
      ) : (
        <>
          <div
            className="relative"
            role="img"
            aria-label={`การกระจายคะแนน: ${buckets
              .filter((b) => b.count > 0)
              .map((b) => `${b.range_start}–${b.range_start + step - 1} ${b.count} คน`)
              .join(", ")}${hasPin ? ` · คะแนนของคนนี้ ${highlightScore}` : ""}`}
          >
            {/* ชื่อโซน — แถวแยกเหนือกราฟ ไม่ให้ชนตัวเลขบนหัวแท่ง */}
            <div className="relative h-5" aria-hidden>
              {zones.map((z) => (
                <span
                  key={z.label}
                  className="absolute top-0 px-1.5 text-label-sm font-semibold truncate"
                  style={{ left: `${pct(z.from)}%`, width: `${pct(z.to) - pct(z.from)}%`, color: z.color }}
                  title={
                    z.from === 0
                      ? `ต่ำกว่า ${z.to}`
                      : z.to === top
                        ? `เกิน ${z.from}`
                        : `${z.from}–${z.to}`
                  }
                >
                  {z.label}
                </span>
              ))}
            </div>

            <div className={compact ? "relative h-28" : "relative h-40"}>
              {/* พื้นโซน */}
              {zones.map((z, i) => (
                <div
                  key={z.label}
                  aria-hidden
                  className={`absolute inset-y-0 ${i === 0 ? "rounded-l-lg" : ""} ${
                    i === zones.length - 1 ? "rounded-r-lg" : ""
                  }`}
                  style={{
                    left: `${pct(z.from)}%`,
                    width: `${pct(z.to) - pct(z.from)}%`,
                    background: `linear-gradient(to top, ${tint(z.color, 14)}, ${tint(z.color, 3)})`,
                  }}
                />
              ))}

              {/* เส้นแบ่งแบนด์ — เส้นประบาง ไม่แย่งสายตาจากแท่ง */}
              {lines.map((l) => (
                <div
                  key={l.at}
                  aria-hidden
                  className="absolute inset-y-0 border-l-2 border-dashed -translate-x-px"
                  style={{ left: `${pct(l.at)}%`, borderColor: l.color }}
                />
              ))}

              {/* แท่ง — เว้นที่ด้านบนไว้ให้ตัวเลขบนหัวแท่งสูงสุด */}
              <div className={`relative flex items-end gap-1.5 h-full ${compact ? "pt-5" : "pt-6"}`}>
                {buckets.map((b, i) => {
                  const h = max > 0 ? (b.count / max) * 100 : 0;
                  const mine = i === pinBucket;
                  return (
                    <div
                      key={b.range_start}
                      className="flex-1 h-full flex flex-col justify-end items-center"
                      title={`คะแนน ${b.range_start}–${
                        i === buckets.length - 1 ? top : b.range_start + step - 1
                      }: ${b.count} คน`}
                    >
                      {b.count > 0 && (
                        <span
                          className={`text-label-md leading-none mb-1.5 font-semibold ${
                            mine ? "text-primary" : "text-on-surface"
                          }`}
                        >
                          {b.count}
                        </span>
                      )}
                      <div
                        className={`w-full max-w-[72px] rounded-t-xl bg-gradient-to-t shadow-sm transition-opacity hover:opacity-90 ${
                          mine
                            ? "from-primary to-primary/70 ring-2 ring-primary/40"
                            : hasPin
                              ? "from-primary/35 to-primary/15"
                              : "from-primary/80 to-primary/40"
                        }`}
                        // ความสูงคำนวณจากข้อมูล ไม่ใช่สี · ขั้นต่ำ 3% ให้ช่วงที่มี 1 คนยังเห็นเป็นแท่ง
                        style={{ height: `${b.count > 0 ? Math.max(h, 3) : 0}%` }}
                      />
                    </div>
                  );
                })}
              </div>
            </div>

            {/* แกนคะแนน — ตัวเลขเส้นแบ่งเป็นตัวหนาสีเดียวกับเส้น
                จอแคบเหลือแค่ 0 · เส้นแบ่งแบนด์ · ค่าสูงสุด — สิบเอ็ดตัวเลขบนจอมือถือชนกัน
                จนอ่านไม่ออก (90 กับ 100 ทับกันตรง ๆ) และตัวที่เหลือคือตัวที่มีความหมาย */}
            <div className="relative h-5 mt-1 border-t border-outline/30" aria-hidden>
              {Array.from({ length: buckets.length + 1 }, (_, i) => i * step).map((v) => {
                const line = lines.find((l) => l.at === v);
                const always = v === 0 || v === top || line != null;
                return (
                  <span
                    key={v}
                    className={`absolute top-1 text-[11px] leading-none ${
                      v === 0 ? "" : v === top ? "-translate-x-full" : "-translate-x-1/2"
                    } ${line ? "font-bold" : "text-outline"} ${
                      always ? "" : "hidden sm:inline"
                    }`}
                    style={{ left: `${pct(v)}%`, ...(line ? { color: line.color } : {}) }}
                  >
                    {v}
                  </span>
                );
              })}
            </div>

            {/* หมุดคะแนนของคนนี้ — ชิดซ้าย/ขวาเมื่ออยู่ใกล้ขอบ กันป้ายล้นการ์ด */}
            {hasPin && (
              <div className="relative h-9" aria-hidden>
                <div
                  className={`absolute top-0 flex flex-col ${
                    pct(highlightScore as number) < 15
                      ? "items-start"
                      : pct(highlightScore as number) > 85
                        ? "items-end -translate-x-full"
                        : "items-center -translate-x-1/2"
                  }`}
                  style={{ left: `${pct(highlightScore as number)}%` }}
                >
                  <span className="material-symbols-outlined text-primary text-[18px] leading-none">
                    arrow_drop_up
                  </span>
                  <span className="text-label-sm font-semibold text-primary whitespace-nowrap px-2 py-0.5 rounded-full bg-primary/15">
                    คะแนนของคนนี้ {highlightScore}
                  </span>
                </div>
              </div>
            )}
          </div>
        </>
      )}
      {children}
    </div>
  );
}
