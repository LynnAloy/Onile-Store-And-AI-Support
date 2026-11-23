import asyncio
import json

from .errors import AppError
from .model import SYSTEM_PROMPT


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def fit_health(profile, budget):
    result, omitted = {}, []
    # Keep complete fields; never truncate a negation or an allergy list halfway.
    priority = ("age", "gender", "heightCm", "weightKg", "bmi", "allergiesText",
                "medicationsText", "medicalHistory", "medicalHistoryText", "lifestyleText", "healthNotes")
    for key in priority:
        if key not in profile:
            continue
        candidate = {**result, key: profile[key]}
        if len(encoded(candidate)) <= budget:
            result = candidate
        else:
            omitted.append(key)
    return result, omitted


async def prepare_context(app, conversation, message, user, token, binding, knowledge_revision):
    settings = app.state.settings
    profile = {}
    if binding["enabled"]:
        data = await app.state.identity.personalization(token, details=True)
        if (data["enabled"], data["revision"]) != (binding["enabled"], binding["revision"]):
            raise AppError(409, "PERSONALIZATION_CHANGED", "健康资料或授权已改变，请重新发送")
        profile = data.get("profile", {})
    if settings.rag_enabled:
        search = await app.state.retriever.search(message)
    else:
        search = {"citations": [], "retrieval": {"mode": "disabled", "knowledgeRevision": 0}}
    if search["retrieval"]["knowledgeRevision"] != knowledge_revision:
        raise AppError(409, "KNOWLEDGE_CHANGED", "知识库已更新，请重新发送")
    available = max(0, settings.context_char_limit - len(SYSTEM_PROMPT) - len(message) - 320)
    health_budget = min(1400, available // 2 if search["citations"] else available)
    health, omitted = fit_health(profile, health_budget)
    available -= len(encoded(health)) + 120
    citations = []
    for item in search["citations"]:
        candidate = {key: value for key, value in item.items() if key != "matchedText"}
        if len(encoded(candidate)) > available:
            candidate["excerpt"] = item["matchedText"]
        if len(encoded(candidate)) > available:
            continue
        candidate["id"] = "S" + str(len(citations) + 1)
        citations.append(candidate)
        available -= len(encoded(candidate))
    context_data = {
        "userReportedHealth": health, "omittedHealthFields": omitted,
        "knowledgeSources": citations, "retrievalMode": search["retrieval"]["mode"],
    }
    history_budget = max(len(message), available + len(message))
    messages = await asyncio.to_thread(
        app.state.store.context, user, conversation, message,
        settings.context_turn_limit, history_budget,
        binding["revision"] if binding["enabled"] else None, knowledge_revision,
    )
    return {
        "messages": messages, "contextData": context_data,
        "metadata": {"citations": citations, "retrieval": search["retrieval"],
                     "personalizationApplied": binding["enabled"],
                     "profileRevision": binding["revision"], "omittedHealthFields": omitted},
    }
