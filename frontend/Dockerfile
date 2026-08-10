# TalentMatch AI — Frontend (Next.js dev)
FROM node:20-alpine

WORKDIR /app

# ติดตั้ง deps ก่อน copy โค้ด (ใช้ layer cache); mount ทับตอน dev ผ่าน compose
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev"]
