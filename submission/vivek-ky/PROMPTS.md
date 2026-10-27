# AI Collaboration Log — Inventory Reservation System

## Prompt Evolution & Design Decisions

### 1. Initial Requirements Analysis
**Prompt**: The user provided a detailed spec for a flash sale inventory reservation system with 5 milestones (M1-M5), concurrency requirements, and Java/Spring Boot tech stack.

**Decision**: Implemented all core milestones using Spring Boot 3.3, JPA with pessimistic row-level locking, and PostgreSQL. Chose **per-SKU** locking over a single global lock for maximum throughput — different SKUs are independent, so they shouldn't block each other.

### 2. Lombok → Removed
**Problem**: Java 24 runtime on the development machine wasn't compatible with the Lombok version bundled via Spring Boot 3.3.5's dependency management. Lombok annotation processor failed to generate getters/setters/builders.

**Resolution**: Removed all `@Getter`, `@Setter`, `@Builder`, and `@NoArgsConstructor`/`@AllArgsConstructor` annotations. Replaced with explicit getters, setters, and constructors. This also makes the code more reviewable (no hidden generated code during PR reviews).

### 3. TTL Expiry Exception Type Bug
**Problem**: When the background `@Scheduled` sweeper expired a reservation before the user called `/confirm`, the `confirm()` method saw status `EXPIRED` and threw `IllegalReservationStateException` (400 Bad Request). The test expected `ReservationExpiredException` (410 Gone).

**Fix**: Changed the already-EXPIRED branch in `confirm()` to throw `ReservationExpiredException` instead. Semantically, "already expired" and "just expired now" should both return `410 Gone` — the user's reservation timed out either way.

### 4. Idempotency Design
**Decision**: Used `X-Idempotency-Key` as a request header, checked at the service layer. If a reservation already exists for that key+user combination, the existing reservation is returned without any stock change. This is checked **before** acquiring the pessimistic lock — a fast path that doesn't block.

Trade-off considered: Storing idempotency keys in a separate table for O(1) lookup. Decided against it because `ReservationRepository.findByIdempotencyKeyAndUserId()` with a composite index provides the same O(log n) lookup with no additional table.

### 5. Background Expiration Worker Design
**Decision**: `@Scheduled(fixedDelay=1000)` — simple priority-queue-free approach. Queries `PENDING` reservations where `expiresAt <= NOW()` and processes them one-by-one with per-SKU locks.

Alternative considered: Min-heap / PriorityQueue for O(log n) expiry-check timers. Rejected as premature optimization — database-driven sweeps are simpler, persistent across restarts, and the `(status, expiresAt)` composite index makes the query efficient for thousands of pending reservations.

### 6. Invariant Validation
Every inventory report endpoint computes `totalStock == availableStock + reservedStock + soldStock` at call time. The `isInvariantValid` field is exposed in the API response so clients can verify data integrity at a glance.

### 7. Test Strategy
- **100-thread thundering herd**: Verifies exact 10-of-100 successes, zero oversell
- **Per-user quota race**: Verifies atomic enforcement under concurrent same-user requests
- **TTL expiry**: Verifies both background sweeper and lazy (on-confirm) expiry paths
- **Idempotency**: Verifies no double-deduction on retry
- **Lifecycle**: Verifies all state machine transitions and their edge cases

### 8. Maven SSL Certificate Issue
**Problem**: Corporate network / firewall blocking Maven Central SSL certificates with `PKIX path building failed`.

**Workaround**: Used Windows truststore via JVM flags: `-Djavax.net.ssl.trustStore=NUL -Djavax.net.ssl.trustStoreType=Windows-ROOT`. This lets the JVM use Windows' native certificate store which has the corporate CA certificates.