package com.flashsale.inventory.dto;

import java.math.BigDecimal;

/**
 * Real-time inventory snapshot for a single product SKU.
 * Invariant: totalStock == availableStock + reservedStock + soldStock.
 */
public record InventoryReportResponse(
        String sku,
        String name,
        int totalStock,
        int availableStock,
        int reservedStock,
        int soldStock,
        int maxPerUser,
        BigDecimal price,
        boolean invariantValid
) {}