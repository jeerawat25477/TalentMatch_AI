/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // รวมเฉพาะไฟล์ที่ต้องใช้จริงไว้ใน .next/standalone พร้อม node_modules เท่าที่ import ถึง
  // ทำให้อิมเมจโปรดักชันเล็กลงมากและไม่ต้องลง devDependencies ในเครื่องที่รันจริง
  // (Dockerfile.prod พึ่งไฟล์นี้ — ถ้าเอาออก build จะได้อิมเมจที่ไม่มี server.js)
  output: "standalone",
};

export default nextConfig;
