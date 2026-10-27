package com.flashsale.inventory.service;

import com.flashsale.inventory.model.Product;
import com.flashsale.inventory.model.Reservation;
import com.flashsale.inventory.model.ReservationStatus;
import com.flashsale.inventory.repository.ProductRepository;
import com.flashsale.inventory.repository.ReservationRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.List;

/**
 * Background TTL expiration worker.
 *
 * Runs every second (configurable via flashsale.expiration.sweep-interval-ms).
 * Queries PENDING reservations whose TTL has elapsed and atomically expires
 * them, restoring stock to available.
 *
 * Uses per-SKU pessimistic locking (same as the reservation service) so
 * there are no race conditions with concurrent user confirm/cancel operations.
 */
@Component
public class ExpirationScheduler {

    private static final Logger log = LoggerFactory.getLogger(ExpirationScheduler.class);

    private final ReservationRepository reservationRepository;
    private final ProductRepository productRepository;

    public ExpirationScheduler(ReservationRepository reservationRepository, ProductRepository productRepository) {
        this.reservationRepository = reservationRepository;
        this.productRepository = productRepository;
    }

    /**
     * Sweeps expired PENDING reservations every second.
     *
     * Each record is processed individually with a pessimistic lock on the
     * product row.  This guarantees that a user-confirm happening at the
     * same moment cannot race with the expiry — whoever acquires the lock
     * first wins, and the other sees the new status.
     */
    @Scheduled(fixedDelayString = "${flashsale.expiration.sweep-interval-ms:1000}")
    @Transactional
    public void expireStaleReservations() {
        Instant now = Instant.now();
        List<Reservation> expired = reservationRepository.findExpiredPendingReservations(now);

        if (expired.isEmpty()) {
            return;
        }

        int expiredCount = 0;
        for (Reservation reservation : expired) {
            try {
                expireSingle(reservation);
                expiredCount++;
            } catch (Exception e) {
                log.error("Failed to expire reservation {}: {}",
                        reservation.getReservationId(), e.getMessage());
            }
        }

        if (expiredCount > 0) {
            log.info("Expired {} stale reservations this sweep", expiredCount);
        }
    }

    /**
     * Expires a single reservation atomically.
     * Acquires per-SKU lock to serialise with user-triggered confirm/cancel.
     */
    @Transactional
    public void expireSingle(Reservation reservation) {
        // Re-read with the entity attached to *this* transaction
        Reservation fresh = reservationRepository.findByReservationId(reservation.getReservationId())
                .orElse(null);
        if (fresh == null || fresh.getStatus() != ReservationStatus.PENDING) {
            // Already handled by another thread or by confirm/cancel
            return;
        }

        Product product = productRepository.findBySkuWithLock(fresh.getSku())
                .orElse(null);
        if (product == null) {
            return;
        }

        fresh.setStatus(ReservationStatus.EXPIRED);
        reservationRepository.save(fresh);

        product.setReservedStock(product.getReservedStock() - fresh.getQuantity());
        product.setAvailableStock(product.getAvailableStock() + fresh.getQuantity());
        productRepository.save(product);

        log.debug("Expired reservation {} ({} x {})", fresh.getReservationId(), fresh.getQuantity(), fresh.getSku());
    }
}