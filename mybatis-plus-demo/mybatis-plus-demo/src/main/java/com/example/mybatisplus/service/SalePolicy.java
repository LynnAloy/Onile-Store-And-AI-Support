package com.example.mybatisplus.service;

import com.example.mybatisplus.entity.Medicine;
import com.example.mybatisplus.exception.ApiException;
import org.springframework.http.HttpStatus;

public final class SalePolicy {
    private SalePolicy() {}
    public static String reason(Medicine medicine) {
        if (medicine == null) return "商品不存在";
        if (medicine.getName() == null || medicine.getName().isBlank()) return "商品名称无效";
        if (!"APPROVED".equals(medicine.getReviewStatus())) return "商品销售资格尚未审核通过";
        if ("RX".equals(medicine.getSaleClassification())) return "处方商品需独立处方审核，当前流程暂不支持";
        if (!"OTC".equals(medicine.getSaleClassification())) return "商品处方分类未知";
        if (medicine.getReferenceSource() == null || !medicine.getReferenceSource().matches("(https?://|local://)\\S+")
                || medicine.getReviewedBy() == null || medicine.getReviewedBy().isBlank()) return "商品审核依据不完整";
        if (medicine.getQualificationVersion() == null || medicine.getQualificationVersion() < 1) return "商品审核版本无效";
        if (medicine.getPrice() == null || medicine.getPrice().signum() <= 0) return "商品价格无效";
        return null;
    }
    public static void require(Medicine medicine) {
        String reason = reason(medicine);
        if (reason != null) throw new ApiException(HttpStatus.CONFLICT, "SALE_NOT_ALLOWED", reason);
    }
}

