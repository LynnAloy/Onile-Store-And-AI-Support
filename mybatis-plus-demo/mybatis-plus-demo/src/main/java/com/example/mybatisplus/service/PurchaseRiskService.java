package com.example.mybatisplus.service;

import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/** Conservative automation gate, not a clinical diagnosis or a medication suitability certificate. */
@Service
public class PurchaseRiskService {
    private final boolean enabled;
    private final MedicineEvidenceService evidence;
    public PurchaseRiskService(@Value("${commerce.evidence-enabled:false}") boolean enabled,MedicineEvidenceService evidence) {
        this.enabled=enabled; this.evidence=evidence;
    }
    public String reason(Map<String,Object> user,List<Map<String,Object>> lines) {
        if (!enabled) return "健康风险门禁未启用，不允许自动扣款";
        Object consent=user.get("ai_profile_consent");
        if (!(Boolean.TRUE.equals(consent) || consent instanceof Number n && n.intValue()==1)) return "未授权使用健康资料，请人工核对后下单";
        if (!(user.get("age") instanceof Number age) || age.intValue()<18 || age.intValue()>=65) return "年龄信息不足或涉及需特别核对的人群，请人工核对";
        Set<String> clear=Set.of("无","无既往病史","无已知过敏","无过敏史","未用药","无当前用药");
        for (String field:List.of("medical_history_text","allergies_text","medications_text")) {
            Object value=user.get(field);
            if (!(value instanceof String text) || !clear.contains(text.trim())) return "病史、过敏史或当前用药存在风险或信息不足，请人工核对";
        }
        Object legacy=user.get("medical_history");
        if (legacy!=null && !Set.of("","[]","null").contains(legacy.toString().replace(" ",""))) return "既往病史记录需要人工核对";
        if (!"无其他健康风险".equals(user.get("health_notes"))) return "其他健康风险尚未明确，请人工核对";
        for (String field:List.of("health_notes","lifestyle_text")) {
            Object value=user.get(field);
            if (value instanceof String text && !text.isBlank() && !Set.of("无","无其他健康风险").contains(text.trim())) return "其他健康资料需要人工核对";
        }
        for (var line:lines) {
            var data=evidence.read(((Number)line.get("medicine_id")).intValue(),((Number)line.get("qualification_version")).longValue());
            if (data.isEmpty()) return "商品缺少当前有效的说明书审核证据，请人工核对";
            if (((Number)line.get("quantity")).intValue()>((Number)data.get("maxUnitsPerOrder")).intValue()) return "超过该商品审核的单次自动购买数量，请人工核对";
        }
        return null;
    }
}
