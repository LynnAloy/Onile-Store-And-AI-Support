import test from "node:test";
import assert from "node:assert/strict";
import { emptyHealthProfile, profilePayload } from "../src/services/profilePayload.mjs";

test("health consent requires an explicit true and payload excludes business fields", () => {
  const health = emptyHealthProfile();
  assert.equal(health.aiProfileConsent, false);
  health.aiProfileConsent = "true";
  health.balance = 999;
  const payload = profilePayload("alice", {}, health);
  assert.equal(payload.health.aiProfileConsent, false);
  assert.equal(payload.basic.userId, "alice");
  assert.equal("balance" in payload.health, false);
});

test("metric input validates boundaries, precision and blank clearing", () => {
  const health = emptyHealthProfile();
  health.heightCm = 180.5;
  health.weightKg = 72;
  assert.equal(profilePayload("alice", {}, health).health.heightCm, 180.5);
  health.heightCm = "";
  assert.equal(profilePayload("alice", {}, health).health.heightCm, null);
  for (const value of [0, 261, 180.55, "not-number", Infinity]) {
    health.heightCm = value;
    assert.throws(() => profilePayload("alice", {}, health));
  }
});

test("self-reported text is retained without truncating negation", () => {
  const health = emptyHealthProfile();
  health.medicalHistoryText = "无既往手术史；其他情况由本人补充。";
  health.medical = ["本人输入病史"];
  health.aiProfileConsent = true;
  const payload = profilePayload("alice", { nickname: "测试" }, health);
  assert.equal(payload.health.medicalHistoryText, health.medicalHistoryText);
  assert.deepEqual(payload.basic.medicalHistory, health.medical);
  assert.equal(payload.health.aiProfileConsent, true);
});

