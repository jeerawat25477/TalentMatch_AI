"use client";

import { useEffect, useState } from "react";
import {
  createEmailTemplate,
  deleteEmailTemplate,
  listEmailTemplates,
} from "@/lib/api";
import { fillTemplate } from "@/lib/types";
import type { EmailDraft, EmailTemplate, TemplateVars } from "@/lib/types";
import { useIsAdmin } from "@/lib/use-me";

/**
 * เลือก/บันทึกเทมเพลตอีเมลที่ใช้ซ้ำ — เป็นชั้นอำนวยความสะดวกล้วน ๆ
 *
 * เลือกแล้ว "เติมช่อง" หัวข้อ/เนื้อความให้เท่านั้น HR ยังต้องอ่าน แก้ได้ และกดส่งเอง
 * (ไม่มี auto-send — ดู CLAUDE.md "Email send is synchronous and HR-gated")
 */
export default function EmailTemplatePicker({
  kind,
  subject,
  body,
  vars,
  onApply,
}: {
  /** ชนิดของอีเมลที่กำลังร่างอยู่ — ใช้กรองไม่ให้เทมเพลตปฏิเสธโผล่ตอนเชิญสัมภาษณ์ */
  kind: EmailDraft["kind"];
  subject: string;
  body: string;
  /** ค่าที่ใช้แทนตัวแปรในเทมเพลต — ตัวที่ยังไม่มีค่า (เช่นยังไม่ได้นัด) ถูกปล่อยไว้ */
  vars: TemplateVars;
  onApply: (subject: string, body: string) => void;
}) {
  const isAdmin = useIsAdmin(); // บัญชีทดลองลบเทมเพลตไม่ได้ (บันทึกใหม่ได้)
  const [templates, setTemplates] = useState<EmailTemplate[]>([]);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    try {
      setTemplates(await listEmailTemplates(kind));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "โหลดเทมเพลตไม่สำเร็จ");
    }
  }

  // โหลดใหม่เมื่อชนิดอีเมลเปลี่ยน (เช่น HR กลับคำตัดสิน ร่างเลยเปลี่ยนจากเชิญเป็นปฏิเสธ)
  useEffect(() => {
    setSelected("");
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  function apply(id: string) {
    setSelected(id);
    const t = templates.find((x) => x.id === id);
    if (!t) return;
    // แทนค่าตัวแปรตอนเลือก แล้วโยนให้หน้าแม่เติมลงช่อง — HR แก้ต่อได้ตามปกติ
    onApply(
      fillTemplate(t.subject_template, vars),
      fillTemplate(t.body_template, vars),
    );
  }

  async function saveCurrent() {
    const name = window.prompt("ตั้งชื่อเทมเพลตนี้", "")?.trim();
    if (!name) return;
    setBusy(true);
    setError(null);
    try {
      // บันทึก "ข้อความที่เห็นอยู่ตอนนี้" ตรง ๆ — ถ้า HR อยากให้ใช้ซ้ำได้กับคนอื่น
      // ให้พิมพ์ {candidate_name} / {job_title} ไว้เอง (มีคำใบ้ใต้ปุ่ม)
      await createEmailTemplate({
        name,
        kind,
        subject_template: subject,
        body_template: body,
      });
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "บันทึกเทมเพลตไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    const t = templates.find((x) => x.id === selected);
    if (!t || !confirm(`ลบเทมเพลต "${t.name}" ถาวร?`)) return;
    setBusy(true);
    setError(null);
    try {
      await deleteEmailTemplate(t.id);
      setSelected("");
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "ลบเทมเพลตไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg bg-glass/30 p-sm space-y-xs">
      <div className="flex items-end gap-xs flex-wrap">
        <label className="block text-label-sm text-outline flex-1 min-w-[160px]">
          เลือกจากเทมเพลต
          <select
            value={selected}
            onChange={(e) => apply(e.target.value)}
            disabled={busy}
            className="input-glass w-full mt-0.5 disabled:opacity-50"
          >
            <option value="">
              {templates.length === 0
                ? "— ยังไม่มีเทมเพลตที่บันทึกไว้ —"
                : "— เลือกเทมเพลต —"}
            </option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>

        {selected && isAdmin && (
          <button
            onClick={remove}
            disabled={busy}
            title="ลบเทมเพลตที่เลือกอยู่"
            aria-label="ลบเทมเพลตที่เลือกอยู่"
            className="btn-secondary-glass flex-none"
          >
            <span className="material-symbols-outlined text-[18px]">delete</span>
          </button>
        )}

        <button
          onClick={saveCurrent}
          disabled={busy || !subject || !body}
          className="btn-secondary-glass flex-none disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-[18px]">bookmark_add</span>
          บันทึกเป็นเทมเพลต
        </button>
      </div>

      <p className="text-label-sm text-outline">
        ใช้ <code className="text-on-surface-variant">{"{candidate_name}"}</code>,{" "}
        <code className="text-on-surface-variant">{"{interview_datetime}"}</code>,{" "}
        <code className="text-on-surface-variant">{"{interview_location}"}</code> และ{" "}
        <code className="text-on-surface-variant">{"{job_title}"}</code>{" "}
        ในเทมเพลตได้ ระบบจะแทนค่าให้ตอนเลือกใช้
      </p>

      {error && (
        <p className="text-error text-label-sm" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
