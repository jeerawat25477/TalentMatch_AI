"""ตัวจำกัดอัตราการเรียกแบบ sliding window (in-memory).

มีตัวจำกัดอยู่แล้วใน auth.py สำหรับ login แต่ตัวนั้นผูกกับ dict ระดับโมดูลและเรียก
time.time() อยู่ข้างใน ทดสอบได้ยาก ที่นี่จึงรับทั้ง `bucket` และ `now` เป็นพารามิเตอร์
ทำให้เป็นฟังก์ชันบริสุทธิ์ที่เทสได้โดยไม่ต้อง mock เวลา — แนวเดียวกับ `_deletion_blocker`
/ `_is_stalled` / `_bulk_partition` ที่แยกกฎออกจาก I/O

⚠️ ต่างจาก login โดยตั้งใจ: login นับเฉพาะครั้งที่ "ผิด" แล้วล้างทิ้งเมื่อสำเร็จ เพราะกัน
brute force ส่วนตัวนี้คุมค่าใช้จ่าย (โควตา LLM) จึงต้องนับ **ทุกครั้งที่เรียก** ไม่ว่าผล
จะสำเร็จหรือไม่ การตรวจกับการบันทึกจึงรวมเป็นฟังก์ชันเดียว แยกกันไม่ได้

หมายเหตุ: เป็น state ในโปรเซส เหมือน rate limit ล็อกอินและทะเบียน active ของ runner
ใช้ได้กับ backend เรพลิกาเดียว — ย้ายไป Redis พร้อมกันทั้งชุดตามที่ 04_security.md ระบุไว้
"""


def hit_and_check(
    bucket: dict[str, list[float]],
    key: str,
    now: float,
    limit: int,
    window_sec: float,
) -> bool:
    """บันทึกการเรียกครั้งนี้ แล้วบอกว่ายังอยู่ในเพดานหรือไม่.

    คืน True = ผ่าน (เรียกได้) · False = เกินเพดานแล้ว
    ครั้งที่เกินก็ยังถูกบันทึก โดยตั้งใจ — การกดรัวต่อจะยิ่งยืดเวลารอออกไป
    ซึ่งเป็นพฤติกรรมที่ต้องการของตัวคุมค่าใช้จ่าย
    """
    recent = [t for t in bucket.get(key, []) if now - t < window_sec]
    recent.append(now)
    bucket[key] = recent
    return len(recent) <= limit


def retry_after_sec(
    bucket: dict[str, list[float]], key: str, now: float, window_sec: float
) -> int:
    """อีกกี่วินาทีถึงจะมีสิทธิ์เรียกได้อีก — เอาไปบอกผู้ใช้ว่าให้รอเท่าไหร่.

    คิดจากรายการที่เก่าที่สุดที่ยังอยู่ในหน้าต่าง เพราะพอมันหลุดหน้าต่างไป
    จำนวนคงเหลือจะลดลงหนึ่ง
    """
    recent = [t for t in bucket.get(key, []) if now - t < window_sec]
    if not recent:
        return 0
    return max(1, int(window_sec - (now - min(recent))) + 1)
