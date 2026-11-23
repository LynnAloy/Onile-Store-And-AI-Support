package com.example.mybatisplus.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.math.BigDecimal;
import java.util.List;

public final class CommerceRequests {
    private CommerceRequests() {}
    public record Policy(@NotNull Boolean enabled, @NotNull @DecimalMin("0.01")
            @DecimalMax("99999999.99") @Digits(integer=8,fraction=2) BigDecimal perOrderLimit,
            @NotNull @DecimalMin("0.01") @DecimalMax("99999999.99")
            @Digits(integer=8,fraction=2) BigDecimal dailyLimit, @NotNull @Min(0) Long expectedVersion,
            @Size(max=72) String password) {}
    public record Turn(@NotBlank @Pattern(regexp="[a-zA-Z0-9-]{36}") String turnId,
            @NotBlank @Size(max=64) String conversationId, @NotBlank @Size(max=4000) String message) {}
    public record Item(@Min(1) int medicineId, @Min(1) @Max(99) int quantity) {}
    public record Execute(@NotEmpty @Size(max=10) List<@Valid Item> items) {}
    public record Review(@NotNull @Min(0) Long expectedVersion,
            @NotBlank @Pattern(regexp="OTC|RX|UNKNOWN") String classification,
            @NotBlank @Pattern(regexp="APPROVED|PENDING") String reviewStatus,
            @Size(max=255) String referenceSource) {}
    public record Stock(@NotNull @Min(0) Long expectedVersion, @NotNull @Min(0) Integer expectedStock, @NotNull @Min(0) Integer stock,
            @NotBlank @Size(max=200) String reason) {}
}
