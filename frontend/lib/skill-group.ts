// กลุ่มทักษะ "ข้อใดข้อหนึ่ง" — backend เก็บเป็นข้อความเดียวคั่นด้วย "|" เช่น "PyTorch | TensorFlow"
// นับเป็น 1 ข้อในคะแนน มีตัวใดตัวหนึ่งก็ผ่าน (backend/app/agents/skills.py::alternatives)
// ที่นี่แค่แปลงไปมาเพื่อแสดงผลและรับค่าที่ HR พิมพ์ — ไม่เทียบทักษะหรือคิดคะแนนเอง

export const GROUP_SEP = "|";

/** ตัวเลือกในกลุ่ม (ทักษะธรรมดาได้รายการตัวเดียว) */
export function alternatives(skill: string): string[] {
  return skill
    .split(GROUP_SEP)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** ข้อความสำหรับคนอ่าน: "PyTorch | TensorFlow" → "PyTorch หรือ TensorFlow" */
export function skillLabel(skill: string): string {
  const alts = alternatives(skill);
  return alts.length ? alts.join(" หรือ ") : skill;
}

/**
 * แปลงข้อความที่ HR พิมพ์ในช่องเพิ่มทักษะ
 * - จุลภาค/ขึ้นบรรทัด = หลายรายการ
 * - "หรือ" หรือ "|" ภายในรายการ = กลุ่มเดียว ("PyTorch หรือ TensorFlow" → "PyTorch | TensorFlow")
 * ไม่รับคำว่า "or" ภาษาอังกฤษ — ชื่อทักษะจริงบางชื่อมีคำนี้ได้ ส่วน "หรือ" ไม่ใช่ชื่อทักษะ
 */
export function splitSkillInput(text: string): string[] {
  return text
    .split(/[,\n]/)
    .map((part) => alternatives(part.replace(/\s*หรือ\s*/g, GROUP_SEP)).join(` ${GROUP_SEP} `))
    .filter(Boolean);
}
