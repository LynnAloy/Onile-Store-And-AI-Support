package com.example.mybatisplus.entity;
import lombok.Data;
import java.math.BigDecimal;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

@Data
@TableName("medicines")
public class Medicine {
    @TableId(type = IdType.AUTO)
    private Integer id;
    private String name;
    private BigDecimal price;
    private Integer stock;
    private String saleClassification;
    private String reviewStatus;
    private String referenceSource;
    private String reviewedBy;
    private Long qualificationVersion;
    public boolean isDraftEligible() {
        return com.example.mybatisplus.service.SalePolicy.reason(this) == null && stock != null && stock > 0;
    }
    public String getDraftBlockedReason() {
        String reason = com.example.mybatisplus.service.SalePolicy.reason(this);
        return reason != null ? reason : stock == null || stock <= 0 ? "当前商品无库存" : "";
    }
}
