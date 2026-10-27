package com.flashsale.inventory.model;

import jakarta.persistence.*;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.math.BigDecimal;

/**
 * Represents a flash-sale product with stock counters and per-user quota.
 *
 * Invariant enforced at all times:
 *   totalStock == availableStock + reservedStock + soldStock
 */
@Entity
@Table(name = "products")
public class Product {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @NotBlank
    @Column(nullable = false, unique = true, length = 64, updatable = false)
    private String sku;

    @NotBlank
    @Column(nullable = false)
    private String name;

    @Min(0)
    @Column(name = "total_stock", nullable = false)
    private int totalStock;

    @Min(0)
    @Column(name = "available_stock", nullable = false)
    private int availableStock;

    @Min(0)
    @Column(name = "reserved_stock", nullable = false)
    private int reservedStock;

    @Min(0)
    @Column(name = "sold_stock", nullable = false)
    private int soldStock;

    @Min(1)
    @Column(name = "max_per_user", nullable = false)
    private int maxPerUser;

    @NotNull
    @Column(nullable = false, precision = 10, scale = 2)
    private BigDecimal price;

    @Version
    @Column(nullable = false)
    private Long version; // optimistic locking backup

    public Product() {
    }

    public Product(String sku, String name, int totalStock, int availableStock,
                   int reservedStock, int soldStock, int maxPerUser, BigDecimal price) {
        this.sku = sku;
        this.name = name;
        this.totalStock = totalStock;
        this.availableStock = availableStock;
        this.reservedStock = reservedStock;
        this.soldStock = soldStock;
        this.maxPerUser = maxPerUser;
        this.price = price;
    }

    /**
     * Returns true if the inventory invariant holds.
     */
    @Transient
    public boolean isInvariantValid() {
        return totalStock == availableStock + reservedStock + soldStock;
    }

    public Long getId() {
        return id;
    }

    public String getSku() {
        return sku;
    }

    public void setSku(String sku) {
        this.sku = sku;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public int getTotalStock() {
        return totalStock;
    }

    public void setTotalStock(int totalStock) {
        this.totalStock = totalStock;
    }

    public int getAvailableStock() {
        return availableStock;
    }

    public void setAvailableStock(int availableStock) {
        this.availableStock = availableStock;
    }

    public int getReservedStock() {
        return reservedStock;
    }

    public void setReservedStock(int reservedStock) {
        this.reservedStock = reservedStock;
    }

    public int getSoldStock() {
        return soldStock;
    }

    public void setSoldStock(int soldStock) {
        this.soldStock = soldStock;
    }

    public int getMaxPerUser() {
        return maxPerUser;
    }

    public void setMaxPerUser(int maxPerUser) {
        this.maxPerUser = maxPerUser;
    }

    public BigDecimal getPrice() {
        return price;
    }

    public void setPrice(BigDecimal price) {
        this.price = price;
    }

    public Long getVersion() {
        return version;
    }
}