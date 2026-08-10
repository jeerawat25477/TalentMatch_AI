// TS types สะท้อน backend/app/schemas.py และผลลัพธ์จาก agents

export interface JobRequirement {
  job_title: string;
  min_experience_years: number;
  required_skills: string[];
  preferred_skills: string[];
  education: string;
}

// 'closed' = ปิดรับสมัคร (เช่น รับพนักงานได้แล้ว) ข้อมูลยังอยู่ครบ ไม่ใช่การลบ
export type JobStatus = "open" | "closed";

export interface Job {
  id: string;
  title: string;
  raw_text: string;
  parsed_criteria: JobRequirement | null;
  status: JobStatus;
  closed_at: string | null;
  created_at: string;
}

export interface JobListItem extends Job {
  candidate_count: number;
}

export interface JobDeleteResult {
  id: string;
  deleted_candidates: number;
  deleted_threads: number;
}

export interface CandidateSummary {
  id: string;
  job_id: string;
  /** ไม่มีผลวิเคราะห์ และไม่มีใครกำลังรันให้ — ต้องกด "วิเคราะห์ใหม่" ถึงจะไปต่อ */
  stalled?: boolean;
  full_name: string;
  email: string | null;
  fit_score: number | null;
  audit_status: string | null;
  gap_analysis: GapAnalysis | null;
  created_at: string;
}

/** ผลค้นหาเชิงความหมายจากคลังเวกเตอร์ (GET /api/v1/candidates/search) */
export interface CandidateSearchHit {
  id: string;
  full_name: string;
  email: string | null;
  job_id: string | null;
  job_title: string | null;
  fit_score: number | null;
  /** cosine distance — ยิ่งน้อยยิ่งใกล้เคียง */
  distance: number;
}

export interface GapAnalysis {
  matched_required: string[];
  missing_required: string[];
  matched_preferred: string[];
  missing_preferred: string[];
}

export interface InterviewQuestion {
  question: string;
  expected_answer: string;
}

export interface InterviewPlan {
  // แถวเก่าใน DB เก็บเป็น string[] (ก่อนเพิ่มแนวคำตอบ) จึงรับได้ทั้งสองแบบ
  questions: (InterviewQuestion | string)[];
}

/** แปลงคำถามให้เป็นรูปแบบเดียว — ของเก่าที่เป็นสตริงจะไม่มีแนวคำตอบ */
export function normalizeQuestions(
  plan: InterviewPlan | null | undefined,
): InterviewQuestion[] {
  if (!plan?.questions) return [];
  return plan.questions.map((q) =>
    typeof q === "string" ? { question: q, expected_answer: "" } : q,
  );
}

export interface EmailDraft {
  kind: "invitation" | "rejection";
  subject: string;
  body: string;
}

export interface EmailSendResult {
  candidate_id: string;
  email_sent_to: string;
  email_sent_at: string;
}

export interface ParsedResume {
  full_name: string;
  email: string | null;
  total_experience_years: number;
  skills: string[];
  education: string;
}

/** ผู้สมัครเก่าที่โปรไฟล์คล้ายกัน จาก retrieval agent (RAG) */
export interface SimilarCandidate {
  id: string;
  full_name: string | null;
  job_title: string | null;
  fit_score: number | null;
  distance: number | null;
}

export interface CandidateDetail extends CandidateSummary {
  raw_resume_text: string | null;
  parsed_resume: ParsedResume | null;
  gap_analysis: GapAnalysis | null;
  audit_log: string | null;
  interview_plan: InterviewPlan | null;
  email_draft: EmailDraft | null;
  email_sent_at: string | null;
  email_sent_to: string | null;
  /** จำนวนครั้งที่ส่งอีเมล (รวมส่งซ้ำ) */
  email_send_count: number;
  similar_candidates: SimilarCandidate[] | null;
  graph_status: GraphStatus;
  /** ถ้ารับเข้าเป็นพนักงานแล้ว = id ระเบียนพนักงาน (ให้ปุ่มสลับเป็นลิงก์ดูข้อมูลพนักงาน) */
  employee_id: string | null;
  /** คำตัดสินของ HR ที่บันทึกไว้ (null = ยังไม่ตัดสิน) — ให้ปุ่มโชว์สถานะหลังรีเฟรช */
  hr_decision: Decision | null;
}

export type Decision = "approved" | "rejected";

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface UserInfo {
  username: string;
}

/** สถานะกราฟของผู้สมัคร — บอกว่าการกดปุ่ม HR จะ "เดินต่อ" หรือ "ตัดสินใหม่ทับของเดิม" */
export type GraphStatus = "awaiting_hr" | "completed" | "processing";

// แบนด์คะแนน → ป้ายสถานะ (ตรงกับ router ของ backend และ DESIGN.md)
export type ScoreBand = "pass" | "review" | "fail" | "pending";

// ⚠️ เส้นแบ่ง 50/70 นี้เป็นสำเนาของ backend/app/agents/bands.py ซึ่งเป็นแหล่งความจริง
// แก้ที่นั่นแล้วต้องแก้ที่นี่ด้วย ไม่งั้นป้ายสีจะไม่ตรงกับเส้นทางที่กราฟเดินจริง
export function scoreBand(score: number | null | undefined): ScoreBand {
  if (score == null) return "pending";
  if (score > 70) return "pass";
  if (score >= 50) return "review";
  return "fail";
}

// สี/วงแหวน/ป้าย ของแต่ละแบนด์ — ตาม DESIGN.md (semantic colors) และ mockup
// color/ring อ้าง CSS variable (นิยามใน globals.css ทั้งสองธีม) เพราะค่าที่ฝังเป็น hex
// ใน JS สลับตามโหมดมืดไม่ได้ ส่วน chip ใช้คลาส Tailwind ที่โทเคนสลับให้เองอยู่แล้ว
export const BANDS: Record<
  ScoreBand,
  { color: string; ring: string; label: string; chip: string }
> = {
  pass: {
    color: "var(--band-pass)",
    ring: "conic-gradient(var(--band-pass-ring) 0 100%)",
    label: "ผ่านเกณฑ์",
    chip: "bg-secondary-container/40 text-on-secondary-container",
  },
  review: {
    color: "var(--band-review)",
    ring: "conic-gradient(var(--band-review-ring) 0 100%)",
    label: "Needs Review",
    // ใช้คู่ *-fixed ทั้งพื้นและตัวอักษร — คู่ tertiary ปกติจะกลายเป็นสว่างบนสว่างในโหมดมืด
    chip: "bg-tertiary-fixed text-on-tertiary-fixed-variant",
  },
  fail: {
    color: "var(--band-fail)",
    ring: "conic-gradient(var(--band-fail-ring) 0 100%)",
    label: "ไม่ผ่าน",
    chip: "bg-error-container/60 text-on-error-container",
  },
  pending: {
    color: "var(--band-pending)",
    ring: "conic-gradient(var(--band-pending-ring) 0 100%)",
    label: "กำลังวิเคราะห์…",
    // on-surface-variant ไม่ใช่ outline — outline บนพื้น outline-variant/40 ได้แค่ 4.17:1 ในโหมดมืด
    chip: "bg-outline-variant/40 text-on-surface-variant",
  },
};

// ป้ายสถานะตำแหน่งงาน — สูตรชิปเดียวกับ BANDS (พื้นสีจาง + ตัวอักษรเข้ม, DESIGN.md §Chips)
export const JOB_STATUS: Record<JobStatus, { label: string; chip: string }> = {
  open: {
    label: "เปิดรับ",
    chip: "bg-secondary-container/40 text-on-secondary-container",
  },
  closed: {
    label: "ปิดแล้ว",
    chip: "bg-outline-variant/40 text-on-surface-variant",
  },
};

// ---------- พนักงาน (รับเข้าหลังสัมภาษณ์ผ่าน) ----------
export type EmployeeStatus =
  | "probation"
  | "permanent"
  | "terminated"
  | "suspended";

// ป้ายสถานะพนักงาน — สูตรชิปเดียวกับ JOB_STATUS/BANDS (โทเคนสลับธีมเองอยู่แล้ว)
export const EMPLOYEE_STATUS: Record<
  EmployeeStatus,
  { label: string; chip: string }
> = {
  probation: {
    label: "ทดลองงาน",
    chip: "bg-tertiary-fixed text-on-tertiary-fixed-variant",
  },
  permanent: {
    label: "ประจำ",
    chip: "bg-secondary-container/40 text-on-secondary-container",
  },
  suspended: {
    label: "พักงาน",
    chip: "bg-outline-variant/40 text-on-surface-variant",
  },
  terminated: {
    label: "พ้นสภาพ",
    chip: "bg-error-container/60 text-on-error-container",
  },
};

export interface EmployeeListItem {
  id: string;
  candidate_id: string;
  full_name: string;
  position: string;
  department: string | null;
  status: EmployeeStatus;
  start_date: string | null;
  hired_at: string;
}

export interface EmployeeDetail extends EmployeeListItem {
  job_id: string | null;
  job_title: string | null;
  email: string | null;
  salary: string | null; // NUMERIC มาเป็น string ผ่าน JSON
  probation_end_date: string | null;
  hr_notes: string | null;
  updated_at: string;
}

/** payload ตอนกด "รับเข้าเป็นพนักงาน" — ฟิลด์ว่างได้ backend เติม position ด้วย job.title */
export interface EmployeeCreate {
  position?: string;
  department?: string;
  salary?: number;
  start_date?: string;
  probation_end_date?: string;
  hr_notes?: string;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}
