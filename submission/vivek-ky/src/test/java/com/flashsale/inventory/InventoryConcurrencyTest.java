package com.flashsale.inventory;

import com.flashsale.inventory.model.Product;
import com.flashsale.inventory.model.ReservationStatus;
import com.flashsale.inventory.repository.ProductRepository;
import com.flashsale.inventory.repository.ReservationRepository;
import com.flashsale.inventory.service.ReservationService;
import com.flashsale.inventory.dto.ReservationResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.math.BigDecimal;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

/**
 * High-concurrency stress tests verifying zero overselling and exact invariant.
 *
 * Strategy:
 * — 100 concurrent threads race for 10 items → exactly 10 success, 90 conflict
 * — Per-user quota race: 10 threads from same user on limit=1 → 1 success, 9 conflict
 * — Final inventory invariant must hold: total == available + reserved + sold
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
class InventoryConcurrencyTest {

    @Autowired private ProductRepository productRepository;
    @Autowired private ReservationRepository reservationRepository;
    @Autowired private ReservationService reservationService;

    private static final String SKU = "TEST-SKU";
    private static final int TOTAL_STOCK = 10;
    private static final int THREAD_COUNT = 100;

    @BeforeEach
    void setUp() {
        reservationRepository.deleteAll();
        productRepository.deleteAll();

        Product product = new Product();
        product.setSku(SKU);
        product.setName("Test Product");
        product.setTotalStock(TOTAL_STOCK);
        product.setAvailableStock(TOTAL_STOCK);
        product.setReservedStock(0);
        product.setSoldStock(0);
        product.setMaxPerUser(5);
        product.setPrice(BigDecimal.TEN);
        productRepository.save(product);
    }

    @Test
    void hundredThreadsOnTenStock_shouldProduceExactlyTenSuccesses() throws Exception {
        ExecutorService executor = Executors.newFixedThreadPool(THREAD_COUNT);
        CountDownLatch latch = new CountDownLatch(1);
        ConcurrentHashMap<Integer, Boolean> results = new ConcurrentHashMap<>();

        for (int i = 0; i < THREAD_COUNT; i++) {
            int idx = i;
            executor.submit(() -> {
                try {
                    latch.await();
                    reservationService.reserve(SKU, "user-" + idx, 1, null);
                    results.put(idx, true);
                } catch (Exception e) {
                    results.put(idx, false);
                }
            });
        }

        latch.countDown();
        executor.shutdown();
        assertTrue(executor.awaitTermination(15, TimeUnit.SECONDS), "Tasks did not complete in time");

        long succeeded = results.values().stream().filter(Boolean::booleanValue).count();
        assertEquals(TOTAL_STOCK, succeeded,
                "Exactly " + TOTAL_STOCK + " reservations should succeed, got " + succeeded);

        // Verify invariant
        Product product = productRepository.findBySku(SKU).orElseThrow();
        assertEquals(product.getTotalStock(),
                product.getAvailableStock() + product.getReservedStock() + product.getSoldStock(),
                "Invariant violated: total ≠ available + reserved + sold");
        assertEquals(0, product.getAvailableStock(), "All stock should be reserved");
        assertEquals(TOTAL_STOCK, product.getReservedStock());
    }

    @Test
    void perUserQuota_shouldRejectExcessRequests() throws Exception {
        Product product = productRepository.findBySku(SKU).orElseThrow();
        product.setMaxPerUser(1);
        productRepository.save(product);

        int tcount = 10;
        ExecutorService executor = Executors.newFixedThreadPool(tcount);
        CountDownLatch latch = new CountDownLatch(1);
        ConcurrentHashMap<Integer, Boolean> results = new ConcurrentHashMap<>();

        String sameUser = "user-quota-test";
        for (int i = 0; i < tcount; i++) {
            int idx = i;
            executor.submit(() -> {
                try {
                    latch.await();
                    reservationService.reserve(SKU, sameUser, 1, null);
                    results.put(idx, true);
                } catch (Exception e) {
                    results.put(idx, false);
                }
            });
        }

        latch.countDown();
        executor.shutdown();
        assertTrue(executor.awaitTermination(15, TimeUnit.SECONDS));

        long succeeded = results.values().stream().filter(Boolean::booleanValue).count();
        assertEquals(1, succeeded, "Exactly 1 reservation should succeed when per-user limit is 1");

        Product after = productRepository.findBySku(SKU).orElseThrow();
        assertEquals(1, after.getReservedStock());
        assertEquals(TOTAL_STOCK - 1, after.getAvailableStock());
    }

    @Test
    void zeroOversellAfterConfirmAll() {
        for (int i = 0; i < TOTAL_STOCK; i++) {
            reservationService.reserve(SKU, "user-" + i, 1, null);
        }

        Product p = productRepository.findBySku(SKU).orElseThrow();
        assertTrue(p.isInvariantValid());
        assertEquals(0, p.getAvailableStock());
        assertEquals(TOTAL_STOCK, p.getReservedStock());

        var reservations = reservationRepository.findAll();
        for (var r : reservations) {
            reservationService.confirm(r.getReservationId());
        }

        Product after = productRepository.findBySku(SKU).orElseThrow();
        assertTrue(after.isInvariantValid());
        assertEquals(TOTAL_STOCK, after.getSoldStock());
        assertEquals(0, after.getReservedStock());
        assertEquals(0, after.getAvailableStock());
    }

    @Test
    void ttlExpiryShouldRestoreStock() throws Exception {
        ReservationResponse resp = reservationService.reserve(SKU, "user-1", 3, null);

        Product before = productRepository.findBySku(SKU).orElseThrow();
        assertEquals(TOTAL_STOCK - 3, before.getAvailableStock());
        assertEquals(3, before.getReservedStock());

        // Wait for TTL to expire + sweep
        Thread.sleep(6_000);

        assertThrows(com.flashsale.inventory.exception.ReservationExpiredException.class, () -> {
            reservationService.confirm(resp.reservationId());
        });

        Product after = productRepository.findBySku(SKU).orElseThrow();
        assertEquals(TOTAL_STOCK, after.getAvailableStock(),
                "Stock should be fully restored after TTL expiry");
        assertEquals(0, after.getReservedStock());
        assertTrue(after.isInvariantValid());
    }

    @Test
    void idempotencyKeyShouldPreventDuplicateDeductions() {
        String idempotencyKey = "idem-001";
        ReservationResponse first = reservationService.reserve(SKU, "user-a", 2, idempotencyKey);
        ReservationResponse second = reservationService.reserve(SKU, "user-a", 2, idempotencyKey);

        assertEquals(first.reservationId(), second.reservationId(),
                "Idempotent replay should return the same reservation");

        Product p = productRepository.findBySku(SKU).orElseThrow();
        assertEquals(2, p.getReservedStock(), "Stock should be deducted only once");
    }

    @Test
    void cancelShouldRestoreStockAndBeIdempotent() {
        ReservationResponse resp = reservationService.reserve(SKU, "user-cancel", 5, null);

        reservationService.cancel(resp.reservationId());
        Product mid = productRepository.findBySku(SKU).orElseThrow();
        assertEquals(TOTAL_STOCK, mid.getAvailableStock());
        assertEquals(0, mid.getReservedStock());

        ReservationResponse again = reservationService.cancel(resp.reservationId());
        assertEquals(ReservationStatus.CANCELLED, again.status());

        Product after = productRepository.findBySku(SKU).orElseThrow();
        assertTrue(after.isInvariantValid());
    }

    @Test
    void confirmIsIdempotent() {
        ReservationResponse resp = reservationService.reserve(SKU, "user-confirm", 2, null);
        reservationService.confirm(resp.reservationId());
        ReservationResponse again = reservationService.confirm(resp.reservationId());
        assertEquals(ReservationStatus.CONFIRMED, again.status());

        Product p = productRepository.findBySku(SKU).orElseThrow();
        assertEquals(2, p.getSoldStock(), "Stock should be sold exactly once");
    }

    @Test
    void cannotCancelConfirmedReservation() {
        ReservationResponse resp = reservationService.reserve(SKU, "user-b", 2, null);
        reservationService.confirm(resp.reservationId());

        assertThrows(com.flashsale.inventory.exception.IllegalReservationStateException.class, () -> {
            reservationService.cancel(resp.reservationId());
        });
    }

    @Test
    void invalidSkuShouldThrow404() {
        assertThrows(com.flashsale.inventory.exception.ResourceNotFoundException.class, () -> {
            reservationService.reserve("NONEXISTENT", "user-x", 1, null);
        });
    }

    @Test
    void overflowStockShouldThrowConflict() {
        assertThrows(com.flashsale.inventory.exception.InsufficientStockException.class, () -> {
            for (int i = 0; i < TOTAL_STOCK; i++) {
                reservationService.reserve(SKU, "user-" + i, 1, null);
            }
            reservationService.reserve(SKU, "overflow-user", 1, null);
        });
    }
}