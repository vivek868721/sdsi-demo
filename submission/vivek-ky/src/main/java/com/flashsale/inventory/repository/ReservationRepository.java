package com.flashsale.inventory.repository;

import com.flashsale.inventory.model.Reservation;
import com.flashsale.inventory.model.ReservationStatus;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * Reservation repository with queries for TTL expiry sweeps and quota checks.
 */
public interface ReservationRepository extends JpaRepository<Reservation, Long> {

    Optional<Reservation> findByReservationId(String reservationId);

    Optional<Reservation> findByIdempotencyKeyAndUserId(String idempotencyKey, String userId);

    /**
     * Sum of quantity held by a user for a given SKU — includes PENDING + CONFIRMED.
     * Used for per-user quota enforcement.
     */
    @Query("""
        SELECT COALESCE(SUM(r.quantity), 0)
        FROM Reservation r
        WHERE r.userId = :userId
          AND r.sku = :sku
          AND r.status IN (:statuses)
    """)
    int sumUserQuantityForSku(
            @Param("userId") String userId,
            @Param("sku") String sku,
            @Param("statuses") List<ReservationStatus> statuses);

    /**
     * Find all PENDING reservations whose TTL has elapsed.
     */
    @Query("SELECT r FROM Reservation r WHERE r.status = 'PENDING' AND r.expiresAt <= :now")
    List<Reservation> findExpiredPendingReservations(@Param("now") Instant now);

    /**
     * Bulk-update expired PENDING reservations to EXPIRED.
     */
    @Modifying
    @Query("UPDATE Reservation r SET r.status = 'EXPIRED' WHERE r.status = 'PENDING' AND r.expiresAt <= :now")
    int expireReservations(@Param("now") Instant now);
}