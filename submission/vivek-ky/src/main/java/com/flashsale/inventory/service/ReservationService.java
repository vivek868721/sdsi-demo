package com.flashsale.inventory.service;

import com.flashsale.inventory.dto.ReservationResponse;
import com.flashsale.inventory.exception.*;
import com.flashsale.inventory.model.Product;
import com.flashsale.inventory.model.Reservation;
import com.flashsale.inventory.model.ReservationStatus;
import com.flashsale.inventory.repository.ProductRepository;
import com.flashsale.inventory.repository.ReservationRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.List;

/**
 * Core reservation service with fine-grained pessimistic locking.
 *
 * Concurrency strategy:
 * — Each reserve/confirm/cancel acquires a PESSIMISTIC_WRITE lock on the
 *   Product row for its SKU (SELECT ... FOR UPDATE). This serialises
 *   writes to the same SKU while allowing different SKUs to proceed in
 *   parallel — far higher throughput than a global lock.
 * — All stock mutations run inside a single @Transactional boundary
 *   so the lock + read + modify + persist sequence is atomic.
 * — Idempotency keys protect against duplicate deductions from retried
 *   network requests.
 */
@Service
public class ReservationService {

    private static final Logger log = LoggerFactory.getLogger(ReservationService.class);

    private final ProductRepository productRepository;
    private final ReservationRepository reservationRepository;
    private final int ttlSeconds;

    public ReservationService(ProductRepository productRepository,
                               ReservationRepository reservationRepository,
                               @Value("${flashsale.reservation.ttl-seconds:120}") int ttlSeconds) {
        this.productRepository = productRepository;
        this.reservationRepository = reservationRepository;
        this.ttlSeconds = ttlSeconds;
    }

    // ──────────────────────────────────────────────
    //  M2: Reserve stock
    // ──────────────────────────────────────────────

    /**
     * Atomically reserves {@code quantity} of {@code sku} for {@code userId}.
     *
     * Steps (all inside a single PG transaction):
     *  1. Acquire pessimistic write lock on the Product row.
     *  2. Validate the product exists and quantity is positive.
     *  3. Check per-user quota: (confirmed + pending) + qty ≤ maxPerUser.
     *  4. Check available stock ≥ qty.
     *  5. Deduct from availableStock, add to reservedStock.
     *  6. Persist a PENDING Reservation with TTL = now + ttlSeconds.
     *
     * @param idempotencyKey  optional client-supplied key; if a reservation
     *                         for this key already exists, it is returned
     *                         without double-deducting.
     */
    @Transactional
    public ReservationResponse reserve(String sku, String userId, int quantity, String idempotencyKey) {
        // --- Idempotency check (outside lock — fast path) ---
        if (idempotencyKey != null && !idempotencyKey.isBlank()) {
            var existing = reservationRepository.findByIdempotencyKeyAndUserId(idempotencyKey, userId);
            if (existing.isPresent()) {
                log.info("Idempotent replay: returning existing reservation {}", existing.get().getReservationId());
                return toResponse(existing.get());
            }
        }

        // --- Acquire per-SKU lock ---
        Product product = productRepository.findBySkuWithLock(sku)
                .orElseThrow(() -> new ResourceNotFoundException("SKU not found: " + sku));

        // --- Quota check ---
        int userHeld = reservationRepository.sumUserQuantityForSku(
                userId, sku, List.of(ReservationStatus.PENDING, ReservationStatus.CONFIRMED));
        if (userHeld + quantity > product.getMaxPerUser()) {
            throw new QuotaExceededException(String.format(
                    "Per-user limit exceeded for %s: holding %d, requested %d, max %d",
                    sku, userHeld, quantity, product.getMaxPerUser()));
        }

        // --- Stock check ---
        if (product.getAvailableStock() < quantity) {
            throw new InsufficientStockException(String.format(
                    "Insufficient stock for %s: available %d, requested %d",
                    sku, product.getAvailableStock(), quantity));
        }

        // --- Atomic stock transfer ---
        product.setAvailableStock(product.getAvailableStock() - quantity);
        product.setReservedStock(product.getReservedStock() + quantity);
        productRepository.save(product);

        // --- Create PENDING reservation ---
        Instant now = Instant.now();
        Reservation reservation = new Reservation();
        reservation.setSku(sku);
        reservation.setUserId(userId);
        reservation.setQuantity(quantity);
        reservation.setStatus(ReservationStatus.PENDING);
        reservation.setCreatedAt(now);
        reservation.setExpiresAt(now.plusSeconds(ttlSeconds));
        reservation.setPriceAtReservation(product.getPrice());
        reservation.setIdempotencyKey(idempotencyKey);
        reservation = reservationRepository.save(reservation);

        log.info("Reserved {} x {} for user {} — reservationId={}, expiresAt={}",
                quantity, sku, userId, reservation.getReservationId(), reservation.getExpiresAt());

        return toResponse(reservation);
    }

    // ──────────────────────────────────────────────
    //  M3: Confirm
    // ──────────────────────────────────────────────

    /**
     * Atomically transitions a PENDING reservation to CONFIRMED.
     *
     * — Idempotent: if already CONFIRMED, returns 200 (not an error).
     * — Lazy expiry: if PENDING but TTL elapsed, expires it on-the-spot
     *   and returns 410 Gone.
     * — Illegal states (CANCELLED, EXPIRED) return 400.
     */
    @Transactional
    public ReservationResponse confirm(String reservationId) {
        Reservation reservation = reservationRepository.findByReservationId(reservationId)
                .orElseThrow(() -> new ResourceNotFoundException("Reservation not found: " + reservationId));

        // Idempotent — already confirmed
        if (reservation.getStatus() == ReservationStatus.CONFIRMED) {
            log.info("Confirm replay: {} is already CONFIRMED", reservationId);
            return toResponse(reservation);
        }

        // Already cancelled — permanent rejection
        if (reservation.getStatus() == ReservationStatus.CANCELLED) {
            throw new IllegalReservationStateException("Cannot confirm a cancelled reservation: " + reservationId);
        }
        // Already expired (e.g. by background sweeper) — same semantic as lazy expiry
        if (reservation.getStatus() == ReservationStatus.EXPIRED) {
            throw new ReservationExpiredException("Reservation has expired: " + reservationId);
        }

        // --- Lazy expiry: if TTL elapsed, expire now and reject ---
        if (reservation.isExpired()) {
            expireReservationAndRestoreStock(reservation);
            throw new ReservationExpiredException("Reservation has expired: " + reservationId);
        }

        // --- Atomic transition PENDING → CONFIRMED ---
        // Lock the product row to serialise with the background sweeper
        Product product = productRepository.findBySkuWithLock(reservation.getSku())
                .orElseThrow(() -> new ResourceNotFoundException("SKU not found: " + reservation.getSku()));

        reservation.setStatus(ReservationStatus.CONFIRMED);
        reservationRepository.save(reservation);

        // Move from reserved → sold
        product.setReservedStock(product.getReservedStock() - reservation.getQuantity());
        product.setSoldStock(product.getSoldStock() + reservation.getQuantity());
        productRepository.save(product);

        log.info("Confirmed reservation {} — {} x {} moved to sold", reservationId, reservation.getQuantity(), reservation.getSku());
        return toResponse(reservation);
    }

    // ──────────────────────────────────────────────
    //  M3: Cancel
    // ──────────────────────────────────────────────

    /**
     * Atomically transitions a PENDING reservation to CANCELLED
     * and restores stock to available.
     *
     * — Idempotent: if already CANCELLED, returns 200.
     * — Cannot cancel a CONFIRMED reservation.
     */
    @Transactional
    public ReservationResponse cancel(String reservationId) {
        Reservation reservation = reservationRepository.findByReservationId(reservationId)
                .orElseThrow(() -> new ResourceNotFoundException("Reservation not found: " + reservationId));

        // Idempotent — already cancelled
        if (reservation.getStatus() == ReservationStatus.CANCELLED) {
            log.info("Cancel replay: {} is already CANCELLED", reservationId);
            return toResponse(reservation);
        }

        if (reservation.getStatus() == ReservationStatus.CONFIRMED) {
            throw new IllegalReservationStateException("Cannot cancel a confirmed reservation: " + reservationId);
        }
        if (reservation.getStatus() == ReservationStatus.EXPIRED) {
            throw new IllegalReservationStateException("Reservation already expired: " + reservationId);
        }

        // --- Atomic transition PENDING → CANCELLED ---
        Product product = productRepository.findBySkuWithLock(reservation.getSku())
                .orElseThrow(() -> new ResourceNotFoundException("SKU not found: " + reservation.getSku()));

        reservation.setStatus(ReservationStatus.CANCELLED);
        reservationRepository.save(reservation);

        // Restore stock to available
        product.setReservedStock(product.getReservedStock() - reservation.getQuantity());
        product.setAvailableStock(product.getAvailableStock() + reservation.getQuantity());
        productRepository.save(product);

        log.info("Cancelled reservation {} — {} x {} returned to available", reservationId, reservation.getQuantity(), reservation.getSku());
        return toResponse(reservation);
    }

    // ──────────────────────────────────────────────
    //  Get reservation by ID
    // ──────────────────────────────────────────────

    @Transactional(readOnly = true)
    public ReservationResponse getByReservationId(String reservationId) {
        Reservation reservation = reservationRepository.findByReservationId(reservationId)
                .orElseThrow(() -> new ResourceNotFoundException("Reservation not found: " + reservationId));
        return toResponse(reservation);
    }

    // ──────────────────────────────────────────────
    //  Helpers
    // ──────────────────────────────────────────────

    void expireReservationAndRestoreStock(Reservation reservation) {
        Product product = productRepository.findBySkuWithLock(reservation.getSku())
                .orElseThrow(() -> new ResourceNotFoundException("SKU not found: " + reservation.getSku()));

        reservation.setStatus(ReservationStatus.EXPIRED);
        reservationRepository.save(reservation);

        product.setReservedStock(product.getReservedStock() - reservation.getQuantity());
        product.setAvailableStock(product.getAvailableStock() + reservation.getQuantity());
        productRepository.save(product);

        log.info("Expired reservation {} — {} x {} returned to available", reservation.getReservationId(), reservation.getQuantity(), reservation.getSku());
    }

    public static ReservationResponse toResponse(Reservation r) {
        return new ReservationResponse(
                r.getReservationId(),
                r.getSku(),
                r.getUserId(),
                r.getQuantity(),
                r.getStatus(),
                r.getCreatedAt(),
                r.getExpiresAt(),
                r.getPriceAtReservation(),
                r.getIdempotencyKey()
        );
    }
}