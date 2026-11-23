package com.example.mybatisplus.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.List;
import lombok.Data;

@Data
public class OrderDTO {
    private String userId;
    @NotBlank @Size(max = 15)
    private String recipientName;
    @NotBlank @Size(max = 50)
    private String recipientAddress;
    @NotBlank @Pattern(regexp = "1[3-9][0-9]{9}")
    private String recipientPhone;
    @Size(max = 200)
    private String note;
    @NotBlank @Pattern(regexp = "[0-9]{6}")
    private String walletPassword;
    @NotEmpty @Size(max = 20)
    private List<@NotNull @Valid OrderItemDTO> items;
}
