package com.example.mybatisplus.entity;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;
import java.math.BigDecimal;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.extension.handlers.FastjsonTypeHandler;
import java.util.*;

@Data
@TableName(value = "users", autoResultMap = true)
public class User {
    @TableId(type = IdType.ASSIGN_UUID)
    private String id;
    private String userId;
    @com.fasterxml.jackson.annotation.JsonIgnore
    @lombok.ToString.Exclude
    private String password;
    private String nickname;
    //private String avatar;
    private String email;
    private String name;
    private Integer age;
    private String gender;
    private String birthday;
    private String phoneNum;
    private String address;
    @TableField(typeHandler = JacksonTypeHandler.class)
    @lombok.ToString.Exclude
    private List<String> medicalHistory;
    @lombok.ToString.Exclude
    private BigDecimal heightCm;
    @lombok.ToString.Exclude
    private BigDecimal weightKg;
    @lombok.ToString.Exclude
    private String medicalHistoryText;
    @lombok.ToString.Exclude
    private String allergiesText;
    @lombok.ToString.Exclude
    private String medicationsText;
    @lombok.ToString.Exclude
    private String lifestyleText;
    @lombok.ToString.Exclude
    private String healthNotes;
    private Boolean aiProfileConsent;
    private Long profileContextVersion;
    private Long profileConsentUpdatedAt;
    private BigDecimal balance;
    private Integer points;
    private Boolean walletActivated;
    @TableField("walletPassword")
    @com.fasterxml.jackson.annotation.JsonIgnore
    @lombok.ToString.Exclude
    private String walletPassword;
    @com.fasterxml.jackson.annotation.JsonIgnore
    @lombok.ToString.Exclude
    private String token;
    @com.fasterxml.jackson.annotation.JsonIgnore
    @lombok.ToString.Exclude
    private String healthToken;
}

