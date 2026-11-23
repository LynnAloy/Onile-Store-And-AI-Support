package com.example.mybatisplus.entity;
import com.example.mybatisplus.dto.UserInfo;
import lombok.Data;
import java.math.BigDecimal;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.extension.handlers.FastjsonTypeHandler;
import java.util.*;


@Data
@TableName("orders")
public class Order {
    @TableId
    private String id;
    private String userId;
    private BigDecimal totalPrice;
    private String status;
    private Date createdAt;
    private String note;
    private String recipientName;
    private String recipientAddress;
    private String recipientPhone;
    @TableField(exist = false)
    private List<OrderItem> items;
}
