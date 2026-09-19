import { test } from "node:test";
import assert from "node:assert/strict";
import { alternatives, skillLabel, splitSkillInput } from "./skill-group";

test("แสดงกลุ่มเป็น หรือ และทักษะธรรมดาคงเดิม", () => {
  assert.equal(skillLabel("PyTorch | TensorFlow | Hugging Face"), "PyTorch หรือ TensorFlow หรือ Hugging Face");
  assert.equal(skillLabel("CI/CD"), "CI/CD");
});

test("alternatives ตัดช่องว่างและช่องเปล่า", () => {
  assert.deepEqual(alternatives(" AWS |  | GCP "), ["AWS", "GCP"]);
});

test("พิมพ์ หรือ แล้วได้กลุ่มเดียว · จุลภาคแยกหลายรายการ", () => {
  assert.deepEqual(splitSkillInput("PyTorch หรือ TensorFlow, Docker"), ["PyTorch | TensorFlow", "Docker"]);
  assert.deepEqual(splitSkillInput("AWS|GCP"), ["AWS | GCP"]);
  assert.deepEqual(splitSkillInput(" , Python ,"), ["Python"]);
});

test("ไม่ตีความ or ภาษาอังกฤษเป็นกลุ่ม", () => {
  assert.deepEqual(splitSkillInput("Oracle"), ["Oracle"]);
  assert.deepEqual(splitSkillInput("A or B"), ["A or B"]);
});
