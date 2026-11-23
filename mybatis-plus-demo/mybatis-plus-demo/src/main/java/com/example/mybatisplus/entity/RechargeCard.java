package com.example.mybatisplus.entity;
import lombok.Data;
import java.math.BigDecimal;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.util.*;

@Data
@TableName("recharge_cards")
public class RechargeCard {
    @TableId
    private String id;
    private BigDecimal amount;
    private Boolean isUsed;
    private String usedBy;
    private Date usedAt;
}
