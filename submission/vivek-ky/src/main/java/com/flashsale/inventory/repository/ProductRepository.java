package com.flashsale.inventory.repository;

import com.flashsale.inventory.model.Product;
import jakarta.persistence.LockModeType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.Optional;

/**
 * Product repository with pessimistic write-lock support for safe stock deductions.
 */
public interface ProductRepository extends JpaRepository<Product, Long> {

    Optional<Product> findBySku(String sku);

    /**
     * Acquires a PESSIMISTIC_WRITE lock on the product row.
     * This serializes concurrent stock-modifying operations on the same SKU
     * while allowing different SKUs to be modified in parallel.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT p FROM Product p WHERE p.sku = :sku")
    Optional<Product> findBySkuWithLock(@Param("sku") String sku);

    /**
     * Returns products without locking — for reporting/read endpoints.
     */
    @Query("SELECT p FROM Product p WHERE p.sku = :sku")
    Optional<Product> findBySkuForRead(@Param("sku") String sku);
}