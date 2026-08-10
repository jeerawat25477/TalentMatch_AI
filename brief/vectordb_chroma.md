# Vector Database Specification: ChromaDB & pgvector

เอกสารนี้ระบุระบบฐานข้อมูลแบบเวกเตอร์ (Vector Database) เพื่อรองรับฟีเจอร์การค้นหาใบสมัครเก่า (Semantic Resume Search) หรือการเปรียบเทียบคำจำกัดความของทักษะ (Skill Semantic Retrieval)

---

## 🔎 1. บทบาทของ Vector Database ในโปรเจคนี้
ในการเปรียบเทียบ Resume กับ JD บางครั้งคำศัพท์สะกดไม่เหมือนกันแต่อาจหมายถึงสิ่งเดียวกัน (เช่น "React Native" กับ "Mobile Hybrid Developer") การคำนวณผ่านเวกเตอร์ระยะห่าง (Cosine Similarity) จะช่วยแก้ไขปัญหานี้ได้:
1.  **คัดเลือกความสามารถของทักษะ (Skill Match)**: ค้นหาประวัติว่ามีทักษะใกล้เคียงกันแทนการ Matching ตัวอักษรแบบดั้งเดิม
2.  **RAG (Retrieval-Augmented Generation)**: ส่งประวัติการทำงานของผู้สมัครเก่าที่มีในคลังไปประเมินร่วมเพื่อค้นหาแคนดิเดตเด่นๆ ในอดีตมารองรับตำแหน่งงานปัจจุบัน

---

## 🛠️ 2. ทางเลือกในการติดตั้ง (Technology Choices)

| ตัวเลือก | ความเหมาะสม | การใช้งานและดูแลรักษา |
| :--- | :--- | :--- |
| **ChromaDB** (Local/Docker) | เหมาะมากในการพัฒนาและส่งโปรเจคจบ | ฟรี รันในเครื่องของตนเอง ไม่ซับซ้อน |
| **pgvector** (Supabase extension) | เหมาะสำหรับการนำไปจำลองใช้จริงบนระบบคลาวด์ | เปิดใช้อัตโนมัติจาก Supabase ไม่ต้องเปิดเซิร์ฟเวอร์แยก |

---

## 💻 3. ตัวอย่างการเขียนโค้ดค้นหาข้อมูล (Python Implementation)

การใช้ **Gemini Embedding API** ร่วมกับ **ChromaDB** บน LangChain:

```python
from langchain_google_genai import GoogleGenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

# 1. กำหนดโมเดลทำ Embeddings (แปลงข้อความยาวๆ เป็น เวกเตอร์ 768 มิติ)
embeddings = GoogleGenAIEmbeddings(model="models/text-embedding-004")

# 2. ฟังก์ชันเพิ่มประวัติผู้สมัครลงคลังเวกเตอร์ (Vector Indexing)
def index_candidate_resumes(candidates_list: list):
    documents = []
    for candidate in candidates_list:
        # สร้างก้อนเอกสารขนาดเล็ก
        doc = Document(
            page_content=candidate["raw_resume_text"],
            metadata={"candidate_id": candidate["id"], "name": candidate["full_name"]}
        )
        documents.append(doc)
    
    # บันทึกลง ChromaDB (โฟลเดอร์ ./chroma_db ในเครื่อง)
    db = Chroma.from_documents(documents, embeddings, persist_directory="./chroma_db")
    print("เพิ่มประวัติลงฐานข้อมูลเวกเตอร์เรียบร้อยแล้ว")

# 3. ฟังก์ชันค้นหาผู้สมัครเก่าที่มีทักษะตรงกับ JD (Semantic Search)
def search_similar_candidates(job_requirements_summary: str, limit: int = 5):
    # เชื่อมฐานข้อมูล Chroma
    db = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)
    
    # ค้นหาด้วยความหมายของข้อความ
    results = db.similarity_search_with_score(job_requirements_summary, k=limit)
    
    recommended_candidates = []
    for doc, score in results:
        # ยิ่งคะแนนระยะห่าง (score) น้อย ยิ่งแสดงว่ามีความใกล้เคียงกันมาก
        recommended_candidates.append({
            "candidate_id": doc.metadata["candidate_id"],
            "name": doc.metadata["name"],
            "distance_score": float(score)
        })
        
    return recommended_candidates
```

---

## 📈 4. ขั้นตอนการตั้งค่าบน Supabase (pgvector DDL)
หากเลือกใช้ Supabase ให้ใช้คำสั่งนี้เพื่อสร้างส่วนเสริมและตารางเวกเตอร์:

```sql
-- 1. เปิดใช้งาน Extension pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. สร้างตารางเก็บ Resume เวกเตอร์
CREATE TABLE resume_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id UUID REFERENCES candidates(id) ON DELETE CASCADE,
    embedding VECTOR(768), -- ขนาดของเวกเตอร์จาก models/text-embedding-004
    content TEXT, -- ข้อความดิบ
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 3. สร้าง Index เพื่อความรวดเร็วในการสืบค้น (HNSW Index)
CREATE INDEX ON resume_embeddings USING hnsw (embedding vector_cosine_ops);
```
