/**
 * ไอคอนหมุน "ระบบกำลังทำงานอยู่" — ชิ้นเดียวใช้ทั้งแอป
 *
 * ที่มา: ปุ่มระหว่างรอมีแต่ข้อความ ("กำลังบันทึก…") ผู้ใช้จึงแยกไม่ออกว่าเครื่องทำงานอยู่หรือค้าง
 * โดยเฉพาะจังหวะที่รอ AI หลายวินาที
 *
 * สีและขนาดรับจากตัวที่ครอบมันอยู่ (currentColor + em) จึงวางในปุ่มสีไหนก็กลมกลืน
 * motion-reduce:animate-none — เครื่องที่ตั้งค่าลดการเคลื่อนไหวจะไม่หมุน แต่ยังเห็นไอคอนกับข้อความ
 */
export default function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={`material-symbols-outlined animate-spin motion-reduce:animate-none ${className}`}
    >
      progress_activity
    </span>
  );
}
