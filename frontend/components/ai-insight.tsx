// AI Insights Module — การ์ดขอบ gradient หลายสีตาม DESIGN.md
// เนื้อหาต้องคำนวณจากข้อมูลจริงเท่านั้น (ห้ามแต่งข้อความลอย ๆ)
export default function AiInsight({
  title = "AI Insight",
  children,
}: {
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="ai-glow-border rounded-2xl bg-glass/70 backdrop-blur-xl p-md shadow-[0_20px_25px_-5px_rgba(0,0,0,0.05)]">
      <div className="flex gap-sm items-start">
        <div className="w-10 h-10 flex-none rounded-xl bg-primary/10 flex items-center justify-center">
          <span className="material-symbols-outlined text-primary">lightbulb</span>
        </div>
        <div className="flex-1 min-w-0">
          <h4 className="text-label-md font-bold text-primary mb-0.5">{title}</h4>
          <div className="text-body-md text-on-surface-variant leading-relaxed">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
