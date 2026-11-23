package com.example.mybatisplus.dto;

import lombok.Data;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;
import java.util.Date;

@Data
@Getter
@Setter
public class WalletDTO {
    private String id;
    private BigDecimal amount;
    private Boolean isUsed;
    private String usedBy;
    private Date usedAt;
}
