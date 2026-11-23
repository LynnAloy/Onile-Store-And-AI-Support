"""M3 real environment checks using only synthetic accounts and health data."""
import json
import sqlite3
import sys
import time
import uuid

from live_smoke import Smoke, check
from local_stack import RUN, ensure_private, query


class ProfileSmoke(Smoke):
    def details(self, consent):
        return {
            "basic": {"userId": self.names[0], "nickname": "合成档案测试", "age": 30,
                      "phoneNum": "13800138000", "medicalHistory": ["仅供测试的自述标签"]},
            "health": {"heightCm": 180, "weightKg": 72, "medicalHistoryText": "仅供测试的既往情况",
                       "aiProfileConsent": consent},
        }

    def frames(self, conversation, token, message, revoke=None):
        result = []
        with self.http.stream("POST", self.base + f"/ai/v1/conversations/{conversation}/messages",
                              headers={"Authorization": "Bearer " + token},
                              json={"requestId": str(uuid.uuid4()), "message": message}) as response:
            check(response.status_code == 200, "Streaming HTTP failed")
            kind = None
            changed = False
            for line in response.iter_lines():
                if line.startswith("event:"):
                    kind = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    result.append((kind, data))
                    if revoke and kind == "delta" and not changed:
                        # A separate HTTP request saves revocation while the stream is active.
                        self.request("PUT", "/api/user/profile/details", revoke, self.details(False))
                        changed = True
        return result

    def run(self):
        with sqlite3.connect(RUN / "knowledge.db") as conn:
            check(conn.execute("SELECT count(*) FROM documents WHERE kind!='platform'").fetchone()[0] == 0,
                  "Knowledge index should contain platform rules only")
        tokens = []
        agents = []
        for name in self.names:
            self.request("POST", "/api/auth/register", data={"userId": name, "password": self.password})
            token = self.request("POST", "/api/auth/login",
                                 data={"userId": name, "password": self.password})["token"]
            tokens.append(token)
            agents.append(self.request("POST", "/api/auth/agent-token", token)["token"])
        a, b = tokens
        agent = agents[0]
        profile = self.request("GET", "/api/user/profile", a)
        check(profile["aiProfileConsent"] is False, "New profiles must default to no consent")
        self.request("PUT", "/api/user/profile/details", b, self.details(True), expected=403)
        self.request("PUT", "/api/user/profile/details", a,
                     {"basic": {}, "health": {"heightCm": 270, "aiProfileConsent": True}}, expected=400)
        self.record("Real MySQL default consent, ownership and bounds")

        self.request("PUT", "/api/user/profile/details", a, self.details(True))
        internal = self.http.get(
                self.java_base + "/internal/ai/v1/personalization-context",
                headers={"Authorization": "Bearer " + agent, "X-AI-Service-Key": self.values["AI_SERVICE_KEY"]})
        check(internal.status_code == 200, "Delegated context unavailable")
        context = internal.json()
        check(context["enabled"] and context["profile"]["bmi"] == 22.2, "Authorized profile mismatch")
        check(not {"phoneNum", "name", "address", "email", "userId"} & context["profile"].keys(),
              "Identity/contact fields leaked")
        check(internal.headers.get("cache-control") == "no-store", "Profile context must not be cached")
        self.record("Java internal whitelist, BMI and no-store context")

        cid = self.request("POST", "/ai/v1/conversations", agent, {"title": "合成M3联调"}, expected=201)["id"]
        frames = self.frames(cid, agent, "根据已授权的档案，仅告诉我填写的身高和体重，不做诊断。")
        check(frames[-1][0] == "done", "Authorized generation failed")
        metadata = next(data for kind, data in frames if kind == "context")
        answer = "".join(data["text"] for kind, data in frames if kind == "delta")
        check(metadata["personalizationApplied"] is True and "180" in answer and "72" in answer,
              "Real model did not receive authorized metrics")
        self.record("FastAPI and real Ollama use explicitly authorized synthetic profile")

        frames = self.frames(cid, agent, "支付密码错误五次会怎样？请依据平台规则简短回答并标注来源。")
        check(frames[-1][0] == "done", "RAG generation failed")
        metadata = next(data for kind, data in frames if kind == "context")
        check(any(c["documentId"] == "platform-wallet" for c in metadata["citations"]), "Wallet citation missing")
        check(all(c["kind"] == "platform" for c in metadata["citations"]), "Non-platform citation")
        self.record("Real embeddings, hybrid retrieval, citations and SSE generation")

        frames = self.frames(cid, agent, "请详细解释我授权的健康档案信息及每个字段的作用，分二十点说明。", revoke=a)
        check(frames[-1][0] == "error" and frames[-1][1]["code"] == "PERSONALIZATION_CHANGED",
              "In-flight revocation must prevent completion")
        self.record("Saving consent withdrawal interrupts a real active model stream")

        frames = self.frames(cid, agent, "平台支持什么功能？简短说明。")
        check(frames[-1][0] == "done", "Post-revocation chat failed")
        metadata = next(data for kind, data in frames if kind == "context")
        check(metadata["personalizationApplied"] is False, "Profile still applied after revocation")
        profile = self.request("GET", "/api/user/profile", a)
        check(profile["heightCm"] == 180 and profile["aiProfileConsent"] is False,
              "Withdrawal should retain owned profile")
        with sqlite3.connect(RUN / "conversations.db") as conn:
            rows = conn.execute("SELECT t.profile_applied,t.status FROM turns t JOIN conversations c "
                                "ON c.id=t.conversation_id WHERE c.user_id=? ORDER BY t.sequence", (self.names[0],)).fetchall()
        check(rows[-1] == (0, "completed") and rows[-2] == (1, "failed"), "Turn binding persistence failed")
        count = query(self.conn, "SELECT count(*) FROM profile_consent_events e JOIN users u ON e.user_id=u.id "
                                "WHERE u.user_id=%s", (self.names[0],))[0][0]
        check(count == 2, "Consent audit mismatch")
        self.record("Post-revocation ordinary chat, retained profile and two consent audit events")


def main():
    ensure_private()
    smoke = ProfileSmoke()
    failure = None
    try:
        smoke.run()
    except Exception as exc:
        failure = str(exc)
    finally:
        try:
            smoke.cleanup()
        except Exception:
            failure = (failure or "") + " Scoped M3 fixture cleanup failed"
    report = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "realServices": True,
              "checks": smoke.results, "passed": failure is None, "failure": failure,
              "syntheticHealthDataOnly": True, "credentialsLogged": False}
    (RUN / "m3-live-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if failure else 0


if __name__ == "__main__":
    sys.exit(main())

