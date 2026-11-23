package com.example.mybatisplus.dto;

import jakarta.validation.constraints.*;
import lombok.Data;

@Data
public class OrderItemDTO {
    @NotNull @Positive
    private Integer medicineId;
    @NotNull @Min(1) @Max(99)
    private Integer quantity;
}
