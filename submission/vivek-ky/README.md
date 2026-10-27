# Inventory Reservation System — Flash Sale

Thread-safe, high-concurrency inventory reservation system preventing overselling during flash sales. Built with Spring Boot 3.3, Java 21, and PostgreSQL.

## Architecture Overview

```
                   ┌─────────────────────────┐
                   │   FastAPI-like REST API  │
                   │   (Spring MVC)           │
                   └───────────┬─────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Inventory       │  │  Reservation    │  │  Expiration     │
│  Controller      │  │  Controller     │  │  Worker         │
│  (GET /report)   │  │  (CRUD lifecycle│  │  (@Scheduled)   │
│                  │  │   + idempotency)│  │                 │
└────────┬─────────┘  └────────┬────────┘  └────────┬────────┘
         │                     │                     │
         └─────────────────────┼─────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  ReservationService  │
                    │  · Per-SKU pessimistic│
                    │    row-level locks    │
                    │  · Atomic state machine│
                    │  · Quota enforcement  │
                    │  · Idempotency        │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │    PostgreSQL 16     │
                    │  · SELECT FOR UPDATE │
                    │  · Row-level locks   │
                    │  · MVCC reads        │
                    └──────────────────────┘
```

## Design Decisions

### Concurrency: Per-SKU Pessimistic Locking (not a global lock)
Each `reserve`/`confirm`/`cancel` operation acquires `LockModeType.PESSIMISTIC_WRITE` on the Product row for the target SKU (`SELECT ... FOR UPDATE`). This serializes writes to the **same SKU** while allowing operations on **different SKUs** to proceed in parallel — maximizing throughput under multi-product load.

### Dual Expiry: Background Sweeper + Lazy Expiry
- **Background Sweeper**: `@Scheduled(fixedDelay=1000)` runs every second, queries PENDING reservations where `expiresAt <= NOW()`, and atomically expires them with per-SKU locks.
- **Lazy Expiry**: When a user hits `/confirm` after TTL has elapsed, the reservation is expired on-the-spot and returns `410 Gone`.

### State Machine
```
  PENDING ──confirm──▶ CONFIRMED (irreversible)
  PENDING ──cancel───▶ CANCELLED (irreversible)
  PENDING ──expire───▶ EXPIRED   (irreversible)
```
All transitions acquire per-SKU locks, ensuring no race between user confirm and background expiry.

### Idempotency
Clients supply `X-Idempotency-Key` header. If a reservation with that key already exists for the user, it's returned without double-deducting stock.

## Quickstart

### Prerequisites
- Java 21+
- Docker (for PostgreSQL)

### 1. Start PostgreSQL
```bash
docker compose up -d
```

### 2. Build & Run
```bash
mvn clean package -DskipTests
mvn spring-boot:run
```

### 3. Run Tests
```bash
mvn test -Djavax.net.ssl.trustStore=NUL -Djavax.net.ssl.trustStoreType=Windows-ROOT
```

The app starts on **http://localhost:8080**. Swagger UI at **http://localhost:8080/swagger-ui.html**.

## API Reference

### Reserve Stock
```bash
curl -X POST http://localhost:8080/api/reservations \
  -H "Content-Type: application/json" \
  -H "X-Idempotency-Key: req-001" \
  -d '{"sku": "PS5-CONSOLE", "userId": "user-101", "quantity": 1}'

# 201 Created
# { "reservationId": "...", "status": "PENDING", "expiresAt": "..." }
```

### Confirm Reservation
```bash
curl -X POST http://localhost:8080/api/reservations/{id}/confirm
# 200 OK — reservation moved to CONFIRMED, stock deducted permanently
```

### Cancel Reservation
```bash
curl -X POST http://localhost:8080/api/reservations/{id}/cancel
# 200 OK — stock restored to available
```

### Get Inventory Report
```bash
curl http://localhost:8080/api/inventory
curl http://localhost:8080/api/inventory/PS5-CONSOLE
# { "sku": "PS5-CONSOLE", "totalStock": 100, "availableStock": 95, ... }
```

## Edge Cases Handled

| Scenario | Status Code | Behavior |
|---|---|---|
| Non-existent SKU | `404 Not Found` | `ResourceNotFoundException` |
| Non-existent reservation ID | `404 Not Found` | `ResourceNotFoundException` |
| Insufficient stock | `409 Conflict` | `InsufficientStockException` |
| Per-user quota exceeded | `409 Conflict` | `QuotaExceededException` |
| Confirm expired reservation | `410 Gone` | `ReservationExpiredException` (lazy + sweeper) |
| Cancel confirmed reservation | `400 Bad Request` | `IllegalReservationStateException` |
| Idempotent retry | `201` + same body | Returns existing reservation |
| Zero/negative quantity | `400 Bad Request` | `@Min(1)` validation on DTO |
| Concurrent user quota bypass | Atomically enforced | Pessimistic lock + quota sum query |

## pgAdmin Connection

1. Open **http://localhost:5050**
2. Login: `admin@flashsale.com` / `admin`
3. Add Server → Host: `postgres`, User: `postgres`, Pass: `postgres`, DB: `flashsale_db`

## Test Suite

```bash
mvn test
```

| Test | Description |
|---|---|
| `hundredThreadsOnTenStock` | 100 threads race for 10 items → exactly 10 succeed |
| `perUserQuota` | 10 threads, same user, limit=1 → exactly 1 succeeds |
| `zeroOversellAfterConfirmAll` | Reserve all stock, confirm all → invariant holds |
| `ttlExpiryShouldRestoreStock` | TTL elapses, stock restored, confirm → 410 |
| `idempotencyKeyShouldPreventDuplicates` | Same key twice → same reservation, stock deducted once |
| `cancelShouldRestoreStockAndBeIdempotent` | Cancel restores stock, second cancel is idempotent |
| `confirmIsIdempotent` | Double confirm → idempotent, stock sold once |
| `cannotCancelConfirmedReservation` | Cancel after confirm → 400 |
| `invalidSkuShouldThrow404` | Non-existent SKU → 404 |
| `overflowStockShouldThrowConflict` | Over-reserve → 409 |

## Stress Test Script

```bash
pip install httpx
python scripts/stress_test.py --threads 100 --stock 10 --sku PS5-CONSOLE
```

## Project Structure

```
submission/vivek-ky/
├── pom.xml
├── docker-compose.yml
├── scripts/
│   └── stress_test.py
├── src/main/java/com/flashsale/inventory/
│   ├── InventoryReservationApplication.java
│   ├── config/
│   │   ├── AppConfig.java
│   │   └── InventorySeeder.java
│   ├── model/
│   │   ├── Product.java
│   │   ├── Reservation.java
│   │   └── ReservationStatus.java
│   ├── repository/
│   │   ├── ProductRepository.java
│   │   └── ReservationRepository.java
│   ├── dto/
│   │   ├── ReserveRequest.java
│   │   ├── ReservationResponse.java
│   │   ├── InventoryReportResponse.java
│   │   └── ErrorResponse.java
│   ├── service/
│   │   ├── InventoryService.java
│   │   ├── ReservationService.java
│   │   └── ExpirationScheduler.java
│   ├── controller/
│   │   ├── InventoryController.java
│   │   └── ReservationController.java
│   └── exception/
│       ├── GlobalExceptionHandler.java
│       └── (5 custom exceptions)
└── src/test/
    └── InventoryConcurrencyTest.java
```