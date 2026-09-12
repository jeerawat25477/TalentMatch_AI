"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import BoardCard, { STAGE_LABEL, STAGE_ORDER } from "@/components/board-card";
import Breadcrumb from "@/components/breadcrumb";
import HireEmployeeDialog from "@/components/hire-employee-dialog";
import JobTabs from "@/components/job-tabs";
import { fetcher, getBoard, setStage } from "@/lib/api";
import type { BoardItem, BoardStage, Job } from "@/lib/types";

export default function HiringBoard() {
  const { id } = useParams<{ id: string }>();

  const { data: job } = useSWR<Job>(`/api/v1/jobs/${id}`, fetcher);
  // ไม่ poll ต่างจากหน้ารายชื่อที่ poll ทุก 4 วิโดยตั้งใจ: หน้านั้นรอผลที่ทยอยมาจากกราฟ
  // ส่วนกระดานเปลี่ยนเฉพาะตอน HR ลงมือเอง — revalidate ระหว่างที่กำลังลากจะทำให้
  // การ์ดกระโดดกลางคัน จึงรีเฟรชตอนกลับมาโฟกัสหน้าต่างและหลังย้ายขั้นเท่านั้น
  const { data, mutate, error, isLoading } = useSWR<BoardItem[]>(
    ["board", id],
    () => getBoard(id),
  );

  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<BoardStage | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [moveError, setMoveError] = useState<string | null>(null);
  // ผู้สมัครที่กำลังจะรับเข้าเป็นพนักงาน — การ์ดยังไม่ย้ายจนกว่าจะกดยืนยันสำเร็จ
  const [hiring, setHiring] = useState<BoardItem | null>(null);

  const items = data ?? [];

  async function move(item: BoardItem, next: BoardStage) {
    if (next === item.stage) return;
    setMoveError(null);

    // "รับเข้าแล้ว" ไม่ใช่ขั้นบนกระดาน แต่เป็นการสร้างระเบียนพนักงานถาวรที่ต้องกรอก
    // ตำแหน่ง/เงินเดือน/วันเริ่มงาน — เปิดโมดัลแทนการยิง PATCH (backend ตอบ 400 อยู่แล้ว)
    if (next === "hired") {
      setHiring(item);
      return;
    }

    // optimistic: ย้ายการ์ดให้เห็นทันที แล้วค่อยยืนยันกับ server
    const before = items;
    setBusyId(item.candidate_id);
    mutate(
      items.map((c) =>
        c.candidate_id === item.candidate_id ? { ...c, stage: next } : c,
      ),
      false,
    );
    try {
      await setStage(item.candidate_id, next);
      await mutate();
    } catch (e) {
      // ล้มเหลวต้องคืนการ์ดกลับที่เดิม **และบอกเหตุผล** ไม่ใช่ปล่อยให้หายเงียบ —
      // ผู้ใช้ต้องรู้ว่าสิ่งที่เพิ่งทำไม่สำเร็จ ไม่งั้นจะเข้าใจว่าย้ายไปแล้ว
      mutate(before, false);
      setMoveError(e instanceof Error ? e.message : "ย้ายขั้นไม่สำเร็จ");
    } finally {
      setBusyId(null);
    }
  }

  return (
    // min-w-0 ที่ทุกชั้นของพ่อแม่ กัน flex item ข้างในดันความกว้างจนทั้งหน้าเลื่อนแนวนอน
    <div className="space-y-md min-w-0">
      <Breadcrumb
        items={[
          { label: "ตำแหน่งงาน", href: "/" },
          { label: job?.title ?? "…", href: `/jobs/${id}` },
          { label: "กระดานติดตาม" },
        ]}
      />

      <div>
        <p className="text-label-sm text-on-surface-variant uppercase tracking-wide">
          กระดานติดตาม
        </p>
        <h1 className="text-headline-lg text-on-surface">{job?.title ?? "…"}</h1>
      </div>

      <JobTabs jobId={id} />

      {moveError && (
        <div
          role="alert"
          className="glass-card rounded-xl p-sm flex items-start gap-xs border-error/40"
        >
          <span className="material-symbols-outlined text-error text-[20px] flex-none">
            error
          </span>
          <p className="text-label-md text-on-surface">{moveError}</p>
        </div>
      )}

      {error && (
        <p className="text-error text-label-md" role="alert">
          โหลดกระดานไม่สำเร็จ — ลองรีเฟรชหน้าอีกครั้ง
        </p>
      )}

      {!isLoading && items.length === 0 && (
        <div className="glass-card rounded-2xl p-lg text-center space-y-xs">
          <span className="material-symbols-outlined text-outline text-[40px]">
            view_kanban
          </span>
          <p className="text-body-md text-on-surface">ยังไม่มีใครอยู่บนกระดาน</p>
          <p className="text-label-md text-on-surface-variant max-w-md mx-auto">
            กระดานจะแสดงเฉพาะผู้สมัครที่ผ่านเกณฑ์อัตโนมัติ หรือที่คุณกดอนุมัติแล้ว
            ส่วนคนที่ยังรอการตัดสินอยู่ในหน้ารายชื่อผู้สมัคร
          </p>
          <Link href={`/jobs/${id}`} className="btn-tonal inline-flex mt-xs">
            ไปหน้ารายชื่อผู้สมัคร
          </Link>
        </div>
      )}

      {items.length > 0 && (
        // กล่องนี้เลื่อนแนวนอนได้เอง ส่วน <body> ต้องไม่เลื่อน — snap ช่วยให้เลื่อนทีละ
        // คอลัมน์บนมือถือแทนที่จะค้างครึ่ง ๆ กลาง ๆ
        <div className="overflow-x-auto snap-x snap-mandatory -mx-margin-mobile px-margin-mobile sm:mx-0 sm:px-0 pb-xs">
          <div className="flex gap-sm items-start">
            {STAGE_ORDER.map((stage) => {
              const cards = items.filter((c) => c.stage === stage);
              // ลากเข้าคอลัมน์ "รับเข้าแล้ว" ได้ (จะเปิดโมดัล) แต่ลากการ์ดที่จ้างแล้วออกไม่ได้
              return (
                <section
                  key={stage}
                  onDragOver={(e) => {
                    // ไม่เรียก preventDefault แล้ว drop จะไม่ทำงานเลย — กับดักคลาสสิกของ HTML5 DnD
                    e.preventDefault();
                    setOver(stage);
                  }}
                  onDragLeave={() => setOver((s) => (s === stage ? null : s))}
                  onDrop={(e) => {
                    e.preventDefault();
                    setOver(null);
                    const cid = e.dataTransfer.getData("text/plain") || dragging;
                    const item = items.find((c) => c.candidate_id === cid);
                    if (item) move(item, stage);
                    setDragging(null);
                  }}
                  className={`snap-start flex-none w-[280px] rounded-2xl p-xs transition-colors ${
                    over === stage
                      ? "bg-primary-container/15 ring-2 ring-primary/50"
                      : "bg-surface-container/40"
                  }`}
                >
                  {/* หัวคอลัมน์ใช้โทนกลางล้วน — สีแบนด์คะแนนสงวนไว้ให้คะแนนเท่านั้น
                      ถ้าเอามาแต่งคอลัมน์ ตาจะอ่านสีผิดว่าเป็นคุณภาพของผู้สมัคร */}
                  <header className="sticky top-0 z-10 flex items-center justify-between gap-base px-xs py-xs mb-xs rounded-xl bg-surface-container-high/80 backdrop-blur-sm">
                    <h2 className="text-label-md font-semibold text-on-surface">
                      {STAGE_LABEL[stage]}
                    </h2>
                    <span className="text-label-sm text-on-surface-variant tabular-nums">
                      {cards.length}
                    </span>
                  </header>

                  <div className="space-y-xs max-h-[calc(100vh-320px)] overflow-y-auto pe-0.5">
                    {cards.map((c) => (
                      <BoardCard
                        key={c.candidate_id}
                        item={c}
                        jobId={id}
                        busy={busyId === c.candidate_id}
                        onDragStart={() => setDragging(c.candidate_id)}
                        onMove={(next) => move(c, next)}
                      />
                    ))}
                    {cards.length === 0 && (
                      <p className="text-label-sm text-outline text-center py-md">
                        ลากการ์ดมาที่นี่
                      </p>
                    )}
                  </div>
                </section>
              );
            })}
          </div>
        </div>
      )}

      {hiring && (
        <HireEmployeeDialog
          candidateId={hiring.candidate_id}
          defaultPosition={job?.title ?? ""}
          onHired={() => {
            // อยู่หน้ากระดานต่อโดยตั้งใจ — ต่างจากหน้ารายละเอียดผู้สมัครที่เด้งไป
            // /employees/{id} เพราะกระดานมีไว้ไล่จัดการหลายคนต่อเนื่อง
            setHiring(null);
            mutate();
          }}
          // กดยกเลิก/Esc = ไม่มีอะไรเปลี่ยน การ์ดยังอยู่คอลัมน์เดิม (เรายังไม่เคยย้ายมัน)
          onClose={() => setHiring(null)}
        />
      )}
    </div>
  );
}
