package com.example.mybatisplus.entity;
import lombok.Data;
import java.math.BigDecimal;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.util.*;

@Data
@TableName("transactions")
public class Transaction {
    @TableId
    private String id;
    private String userId;
    private String type;
    private BigDecimal amount;
    private Integer pointsChange;
    private Date createdAt;
    private String relatedId;
}
