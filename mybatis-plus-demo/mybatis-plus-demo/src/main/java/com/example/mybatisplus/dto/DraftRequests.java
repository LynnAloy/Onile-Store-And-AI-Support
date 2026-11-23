package com.example.mybatisplus.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.List;

public final class DraftRequests {
    private DraftRequests() {}
    public record Item(@NotNull @Min(1) Integer medicineId, @NotNull @Min(1) @Max(99) Integer quantity) {}
    public record Intent(@NotNull @Size(min = 1, max = 10) List<@NotNull @Valid Item> items) {}
    public record Version(@NotNull @Min(1) Long version) {}
    public record Confirm(@NotNull @Min(1) Long version,
            @NotBlank @Size(max = 15) String recipientName,
            @NotBlank @Pattern(regexp = "1[3-9][0-9]{9}") String recipientPhone,
            @NotBlank @Size(max = 50) String recipientAddress) {}
}

