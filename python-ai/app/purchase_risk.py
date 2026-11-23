"""Consent-aware conservative checks. Never emit a clinical 'safe to use' verdict."""
CLEAR = {"无", "无既往病史", "无已知过敏", "无过敏史", "未用药", "无当前用药"}


def assess(context):
    context = context or {}
    profile = context.get("userReportedHealth", {})
    reasons = []
    if not profile:
        reasons.append("健康资料未授权或未提供，需人工核对")
    age = profile.get("age")
    if not isinstance(age, (int, float)) or isinstance(age, bool) or age < 18 or age >= 65:
        reasons.append("年龄信息不足或涉及未成年人")
    for field in ("allergiesText", "medicalHistoryText", "medicationsText"):
        if profile.get(field, "").strip() not in CLEAR:
            reasons.append("病史、过敏史或在用药信息存在风险或尚未明确")
            break
    if profile.get("medicalHistory") or context.get("omittedHealthFields"):
        reasons.append("存在其他病史记录或未纳入复核的资料")
    if profile.get("healthNotes") != "无其他健康风险":
        reasons.append("其他健康风险尚未明确")
    if any(profile.get(field, "").strip() not in {"", "无", "无其他健康风险"} for field in ("healthNotes", "lifestyleText")):
        reasons.append("其他健康资料需要人工核对")
    return {"decision": "MANUAL_REVIEW" if reasons else "NO_RECORDED_BLOCKER",
            "healthProfileUsed": bool(profile), "automaticPurchaseAllowed": not reasons,
            "reasons": reasons, "notice": "仅为已填资料的自动化门禁，不是用药安全或适用性结论"}
