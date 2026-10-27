package com.flashsale.inventory.dto;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;

/**
 * Request body for reserving stock during a flash sale.
 */
public record ReserveRequest(
        @NotBlank(message = "SKU must not be blank")
        String sku,

        @NotBlank(message = "userId must not be blank")
        String userId,

        @Min(value = 1, message = "Quantity must be at least 1")
        int quantity
) {}