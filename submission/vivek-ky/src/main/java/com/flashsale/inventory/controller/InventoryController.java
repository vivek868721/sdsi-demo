package com.flashsale.inventory.controller;

import com.flashsale.inventory.dto.InventoryReportResponse;
import com.flashsale.inventory.service.InventoryService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * Read-only inventory reporting endpoints.
 *
 * Returns O(1) snapshots per SKU with invariant validation.
 */
@RestController
@RequestMapping("/api/inventory")
@Tag(name = "Inventory", description = "Real-time inventory reporting")
public class InventoryController {

    private final InventoryService inventoryService;

    public InventoryController(InventoryService inventoryService) {
        this.inventoryService = inventoryService;
    }

    @GetMapping
    @Operation(summary = "List all products", description = "Returns current stock snapshot for every product")
    public List<InventoryReportResponse> listAll() {
        return inventoryService.listAll();
    }

    @GetMapping("/{sku}")
    @Operation(summary = "Get product by SKU", description = "Returns detailed stock report for a single SKU")
    @ApiResponse(responseCode = "404", description = "SKU not found", content = @Content)
    public InventoryReportResponse getBySku(@PathVariable String sku) {
        return inventoryService.getBySku(sku);
    }
}