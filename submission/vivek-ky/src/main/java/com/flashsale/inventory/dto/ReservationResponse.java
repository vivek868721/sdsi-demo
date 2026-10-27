package com.flashsale.inventory.dto;

import com.flashsale.inventory.model.ReservationStatus;
import java.math.BigDecimal;
import java.time.Instant;

/**
 * Response returned after creating or querying a reservation.
 */
public record ReservationResponse(
        String reservationId,
        String sku,
        String userId,
        int quantity,
        ReservationStatus status,
        Instant createdAt,
        Instant expiresAt,
        BigDecimal priceAtReservation,
        String idempotencyKey
) {}