// ตัวช่วยเรียก FastAPI backend — base URL จาก env (เบราว์เซอร์เรียกตรงที่ :8000)
import { clearToken, getToken, setToken } from "./auth";
import type {
  BulkDecisionResult,
  CandidateDetail,
  CandidateSearchHit,
  CandidateSummary,
  Decision,
  EmailSendResult,
  EmailTemplate,
  EmployeeCreate,
  EmployeeDetail,
  EmployeeListItem,
  EmployeeStatus,
  Job,
  JDReview,
  JobDeleteResult,
  JobListItem,
  JobStatus,
  TokenResponse,
  UserInfo,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// แนบ Authorization ให้ทุก request ถ้ามี token
function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getToken();
  return {
    ...(extra ?? {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

// เซสชันหมด/ไม่มีสิทธิ์ → ล้าง token แล้วเด้งไปหน้า login (ทุกหน้าใช้ request ผ่าน SWR จึงครอบทั้งแอป)
function handleUnauthorized(): void {
  clearToken();
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: authHeaders(init?.headers),
  });
  if (!res.ok) {
    if (res.status === 401) handleUnauthorized();
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ไม่ใช่ JSON */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

// ---------- Auth ----------
export async function login(username: string, password: string): Promise<void> {
  const res = await request<TokenResponse>("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  setToken(res.access_token);
}

export const getMe = () => request<UserInfo>("/api/v1/auth/me");

// ใช้กับ SWR: key เป็น path เต็ม
export const fetcher = <T>(path: string): Promise<T> => request<T>(path);

export const listJobs = () => request<JobListItem[]>("/api/v1/jobs");

export const getJob = (jobId: string) => request<Job>(`/api/v1/jobs/${jobId}`);

export const createJob = (rawText: string) =>
  request<Job>("/api/v1/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ raw_text: rawText }),
  });

// เปิด/ปิดรับสมัคร — ทางเลือกแทนการลบสำหรับงานที่รับพนักงานได้แล้ว
// ตรวจร่าง JD ก่อนโพสต์ — พรีวิวล้วน ๆ ไม่สร้างงานจริง (429 ถ้ากดถี่เกิน, 503 ถ้า AI ล่ม)
export const reviewJD = (rawText: string) =>
  request<JDReview>("/api/v1/jobs/review-jd", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ raw_text: rawText }),
  });

export const setJobStatus = (jobId: string, status: JobStatus) =>
  request<Job>(`/api/v1/jobs/${jobId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });

// ลบถาวร — backend ตอบ 409 ถ้าเคยส่งอีเมลออกไปแล้ว หรือกำลังประมวลผลผู้สมัครอยู่
export const deleteJob = (jobId: string) =>
  request<JobDeleteResult>(`/api/v1/jobs/${jobId}`, { method: "DELETE" });

export const listCandidates = (jobId: string) =>
  request<CandidateSummary[]>(`/api/v1/jobs/${jobId}/candidates`);

// ลบผู้สมัครถาวร (อัปผิดไฟล์/อัปซ้ำ) — backend ตอบ 409 ถ้าเคยส่งอีเมลถึงคนนี้แล้ว
export const deleteCandidate = (candidateId: string) =>
  request<{ id: string; deleted_thread: boolean }>(
    `/api/v1/candidates/${candidateId}`,
    { method: "DELETE" },
  );

// สั่งวิเคราะห์ใหม่สำหรับผู้สมัครที่ค้าง (ใช้ข้อความเรซูเม่ใน DB ไม่ต้องอัปโหลด PDF ซ้ำ)
export const reprocessCandidate = (candidateId: string) =>
  request<{ candidate_id: string; message: string }>(
    `/api/v1/candidates/${candidateId}/reprocess`,
    { method: "POST" },
  );

export const getCandidate = (candidateId: string) =>
  request<CandidateDetail>(`/api/v1/candidates/${candidateId}`);

// ค้นหาผู้สมัครเก่าด้วยความหมาย (pgvector) — ไม่ใช่การจับคำ
export const searchCandidates = (q: string, limit = 10) =>
  request<CandidateSearchHit[]>(
    `/api/v1/candidates/search?q=${encodeURIComponent(q)}&limit=${limit}`,
  );

// ส่งอีเมลจริงถึงผู้สมัคร (HR ยืนยันผู้รับ/หัวข้อ/เนื้อความเอง)
export const sendEmail = (
  candidateId: string,
  data: { to: string; subject: string; body: string },
) =>
  request<EmailSendResult>(`/api/v1/candidates/${candidateId}/email/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

// ---------- เทมเพลตอีเมลที่บันทึกไว้ใช้ซ้ำ ----------
// ชั้นอำนวยความสะดวกล้วน ๆ ไม่เกี่ยวกับการส่งจริง (ยังผ่าน sendEmail ด้านบนเหมือนเดิม)
export const listEmailTemplates = (kind?: EmailTemplate["kind"]) =>
  request<EmailTemplate[]>(
    `/api/v1/email-templates${kind ? `?kind=${kind}` : ""}`,
  );

export const createEmailTemplate = (data: {
  name: string;
  kind: EmailTemplate["kind"];
  subject_template: string;
  body_template: string;
}) =>
  request<EmailTemplate>("/api/v1/email-templates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

export const deleteEmailTemplate = (id: string) =>
  request<{ id: string }>(`/api/v1/email-templates/${id}`, { method: "DELETE" });

export const submitDecision = (
  candidateId: string,
  decision: Decision,
  notes: string,
) =>
  request(`/api/v1/candidates/${candidateId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, notes }),
  });

// ---------- พนักงาน ----------
// รับผู้สมัครเข้าเป็นพนักงาน — backend ตอบ 409 ถ้าเคยรับเข้าแล้ว
// ตัดสินหลายคนด้วยผลเดียวกัน — ตอบ 202 ทันที งานจริงรันเบื้องหลัง
// ผลรายคนดูจากการ poll หน้ารายชื่อเดิม (graph_status เปลี่ยนเป็น completed)
export const bulkDecision = (
  candidateIds: string[],
  decision: Decision,
  notes?: string,
) =>
  request<BulkDecisionResult>("/api/v1/candidates/bulk-decision", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidate_ids: candidateIds, decision, notes }),
  });

export const hireCandidate = (candidateId: string, data: EmployeeCreate) =>
  request<EmployeeDetail>(`/api/v1/candidates/${candidateId}/hire`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });

export const listEmployees = (status?: EmployeeStatus) =>
  request<EmployeeListItem[]>(
    `/api/v1/employees${status ? `?status=${status}` : ""}`,
  );

export const getEmployee = (id: string) =>
  request<EmployeeDetail>(`/api/v1/employees/${id}`);

export const setEmployeeStatus = (
  id: string,
  status: EmployeeStatus,
  note?: string,
) =>
  request<EmployeeDetail>(`/api/v1/employees/${id}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, note }),
  });

// อัปโหลด PDF หลายไฟล์ (multipart) — ใช้ XHR เพื่ออ่าน progress
export function uploadResumes(
  jobId: string,
  files: File[],
  onProgress?: (percent: number) => void,
): Promise<{
  accepted: number;
  candidate_ids: string[];
  /** จำนวนไฟล์ที่ไม่ได้สร้างผู้สมัคร = ซ้ำ + อ่านข้อความไม่ออก */
  skipped: number;
  /** เคยอัปโหลดเข้าตำแหน่งงานนี้แล้ว (เทียบด้วย hash ของไบต์ไฟล์) */
  duplicate_files: string[];
  /** สกัดข้อความไม่ได้ — มักเป็นเรซูเม่สแกน/ถ่ายรูปที่ไม่มีชั้นข้อความ */
  unreadable_files: string[];
}> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/v1/jobs/${jobId}/resumes`);
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new Error(`${xhr.status}: ${xhr.responseText}`));
      }
    };
    xhr.onerror = () => reject(new Error("network error"));
    xhr.send(form);
  });
}
