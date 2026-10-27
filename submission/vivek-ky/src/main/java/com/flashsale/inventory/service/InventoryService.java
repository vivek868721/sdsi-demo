package com.flashsale.inventory.service;

import com.flashsale.inventory.dto.InventoryReportResponse;
import com.flashsale.inventory.exception.ResourceNotFoundException;
import com.flashsale.inventory.model.Product;
import com.flashsale.inventory.repository.ProductRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * Read-only inventory reporting service.
 *
 * All lookups are O(1) by SKU index. No locks needed for reads —
 * PostgreSQL's MVCC provides a consistent snapshot.
 */
@Service
public class InventoryService {

    private static final Logger log = LoggerFactory.getLogger(InventoryService.class);
    private final ProductRepository productRepository;

    public InventoryService(ProductRepository productRepository) {
        this.productRepository = productRepository;
    }

    /**
     * Returns reports for every product in the inventory.
     */
    @Transactional(readOnly = true)
    public List<InventoryReportResponse> listAll() {
        return productRepository.findAll().stream()
                .map(this::toReport)
                .toList();
    }

    /**
     * Returns a single product report by SKU.
     */
    @Transactional(readOnly = true)
    public InventoryReportResponse getBySku(String sku) {
        Product product = productRepository.findBySkuForRead(sku)
                .orElseThrow(() -> new ResourceNotFoundException("SKU not found: " + sku));
        return toReport(product);
    }

    /**
     * Maps a Product entity to an InventoryReportResponse DTO.
     * Always recalculates invariant validity.
     */
    private InventoryReportResponse toReport(Product p) {
        return new InventoryReportResponse(
                p.getSku(),
                p.getName(),
                p.getTotalStock(),
                p.getAvailableStock(),
                p.getReservedStock(),
                p.getSoldStock(),
                p.getMaxPerUser(),
                p.getPrice(),
                p.isInvariantValid()
        );
    }
}