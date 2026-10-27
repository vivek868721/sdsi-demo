package com.flashsale.inventory.model;

import jakarta.persistence.*;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

/**
 * A single stock reservation bound to a user and SKU.
 *
 * Lifecycle: PENDING → CONFIRMED | CANCELLED | EXPIRED
 * PENDING reservations hold stock and have a TTL (expiresAt).
 * Transitions out of PENDING are atomic and irreversible.
 */
@Entity
@Table(name = "reservations", indexes = {
    @Index(name = "idx_reservations_status_expires", columnList = "status, expiresAt"),
    @Index(name = "idx_reservations_user_sku_status", columnList = "userId, sku, status")
})
public class Reservation {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @NotBlank
    @Column(nullable = false, updatable = false, length = 64)
    private String reservationId; // external UUID for idempotency

    @NotBlank
    @Column(nullable = false, updatable = false, length = 64)
    private String sku;

    @NotBlank
    @Column(nullable = false, updatable = false, length = 128)
    private String userId;

    @Min(1)
    @Column(nullable = false)
    private int quantity;

    @NotNull
    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private ReservationStatus status;

    @Column(nullable = false)
    private Instant createdAt;

    @Column(nullable = false)
    private Instant expiresAt;

    @Column(nullable = false, precision = 10, scale = 2)
    private BigDecimal priceAtReservation;

    @Column(length = 128)
    private String idempotencyKey;

    @Version
    @Column(nullable = false)
    private Long version;

    public Reservation() {
    }

    @PrePersist
    public void prePersist() {
        if (this.reservationId == null || this.reservationId.isBlank()) {
            this.reservationId = UUID.randomUUID().toString();
        }
        if (this.createdAt == null) {
            this.createdAt = Instant.now();
        }
    }

    /**
     * Returns true if this reservation's TTL has elapsed while still PENDING.
     */
    @Transient
    public boolean isExpired() {
        return status == ReservationStatus.PENDING && Instant.now().isAfter(expiresAt);
    }

    // --- Getters and Setters ---

    public Long getId() {
        return id;
    }

    public String getReservationId() {
        return reservationId;
    }

    public void setReservationId(String reservationId) {
        this.reservationId = reservationId;
    }

    public String getSku() {
        return sku;
    }

    public void setSku(String sku) {
        this.sku = sku;
    }

    public String getUserId() {
        return userId;
    }

    public void setUserId(String userId) {
        this.userId = userId;
    }

    public int getQuantity() {
        return quantity;
    }

    public void setQuantity(int quantity) {
        this.quantity = quantity;
    }

    public ReservationStatus getStatus() {
        return status;
    }

    public void setStatus(ReservationStatus status) {
        this.status = status;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Instant createdAt) {
        this.createdAt = createdAt;
    }

    public Instant getExpiresAt() {
        return expiresAt;
    }

    public void setExpiresAt(Instant expiresAt) {
        this.expiresAt = expiresAt;
    }

    public BigDecimal getPriceAtReservation() {
        return priceAtReservation;
    }

    public void setPriceAtReservation(BigDecimal priceAtReservation) {
        this.priceAtReservation = priceAtReservation;
    }

    public String getIdempotencyKey() {
        return idempotencyKey;
    }

    public void setIdempotencyKey(String idempotencyKey) {
        this.idempotencyKey = idempotencyKey;
    }

    public Long getVersion() {
        return version;
    }
}