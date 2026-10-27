# Root Cause Analysis (RCA) & Remediation Report
## Incident Reference: PERF-512 | Severity: P0 - BLOCKER

---

### Document Control & Incident Metadata

| Attribute | Details |
| :--- | :--- |
| **Incident ID** | `PERF-512` (Jira) / `INC-89211` (PagerDuty) |
| **Severity / Priority** | **P0 - BLOCKER** (Critical Production Outage / Revenue Degradation) |
| **Target Service** | `order-service` (`com.enterprise.order`) |
| **Connection Pool & Storage** | HikariCP (`HikariPool-1`) on PostgreSQL 15.4 RDS Multi-AZ |
| **Telemetry Dashboard** | [Grafana Hikari-Postgres Telemetry Dashboard](http://grafana.internal:3000/d/perf-prod/hikari-postgres-pool) |
| **Staged Pull Request** | [`fix/PERF-512-order-service-try-with-resources`](https://github.com/enterprise/order-service/pull/1842) |
| **Culprit Commit / Author** | Commit `b8f3a9e` by Alex Dev `<alex.dev@acme-commerce.com>` |
| **Autonomous Agent** | Autonomous PerfRCA Agent v2.4 (Drain Log Clusterer + State Engine) |
| **Institutional Memory Match** | Historical Post-Mortem `OPP-3716` (98.4% Vector Overlap) |
| **Current Status** | **Mitigated & Verified** (Hotfix verified with 100 concurrent threads) |

---

> [!CRITICAL]
> **Production Blast Radius**: Connection pool exhaustion completely starved the `order-service` request pool, dropping query throughput by **-96%** (to 1.8 TPS) and increasing P99 latency by **+21,462%** (to 3,450.0 ms), causing cascading checkout transaction timeouts.

---

## 1. Executive Summary

During continuous telemetry monitoring of the Grafana dashboard (`http://grafana.internal:3000/d/perf-prod/hikari-postgres-pool`), the database connection pool (`HikariPool-1`) supporting `order-service` suffered acute resource starvation. Leased connections surged to 100% capacity (10/10), causing incoming checkout queries to wait up to 30,000ms before timing out with `SQLTransientConnectionException`. P99 query latency degraded by **+21,462%** (surging from 16.5ms to 3,450ms), while query throughput (TPS) collapsed by **-96%** (down to 1.8 TPS).

### Autonomous PerfRCA Agent Diagnosis
* **Telemetry Anomaly**: Classified as `CRITICAL_CONNECTION_POOL_EXHAUSTION`.
* **45,000 Log Clustering**: Clustered application logs using the Drain algorithm. Isolated **39,812 hits (88.5%)** of the HikariPool acquisition timeout template originating specifically from `OrderService.getOrderDetailsFast()`.
* **Institutional Memory**: Matched historical post-mortem `OPP-3716` with **98.4% confidence**.
* **Git Blame**: Blamed commit `b8f3a9e` (Alex Dev) introducing raw unclosed JDBC connections in `OrderService.java`.
* **Remediation**: Synthesized a verified `try-with-resources` patch and staged PR branch `fix/PERF-512-order-service-try-with-resources`.

---

## 2. Telemetry Impact Matrix

| Metric Dimension | Healthy Baseline | Incident Peak | Impact / Degradation Factor | System Threshold / SLA |
| :--- | :--- | :--- | :--- | :--- |
| **Connection Pool Utilization** | `2 / 10` (20%) | `10 / 10` (100%) | **+400%** (Complete Saturation) | Max: 10 connections (`maximumPoolSize`) |
| **P99 Query Latency** | `16.5 ms` | `3,450.0 ms` | **+21,462%** (Critical SLA Breach) | SLA Target: `< 50.0 ms` |
| **P50 Query Latency** | `4.2 ms` | `1,280.0 ms` | **+30,376%** (Severe User Delay) | Target: `< 10.0 ms` |
| **Query Throughput (TPS)** | `45.2 TPS` | `1.8 TPS` | **-96.0%** (Throughput Collapse) | Baseline Expectation: `40 - 55 TPS` |
| **Queued Waiting Threads** | `0 threads` | `84 threads` | **Thread Pool Starvation** | Alert Trigger: `> 5 waiting threads` |
| **Connection Wait Duration** | `1.2 ms` | `30,000.0 ms` | **Timeout Saturation** | HikariCP `connectionTimeout`: 30,000 ms |
| **HTTP 504 / 500 Error Rate** | `0.001%` | `94.2%` | **+9,419x Surge** | SLA: `< 0.05%` error budget |

---

## 3. Performance Mechanics & Queuing Dynamics

```mermaid
flowchart TD
    subgraph Traffic ["Incoming Client Requests (45+ TPS)"]
        Req1["Request 1"]
        Req2["Request 2"]
        ReqN["Request 11..N"]
    end

    subgraph Service ["OrderService.getOrderDetailsFast()"]
        Acq["dataSource.getConnection()"]
        Query["Execute SELECT query"]
        Return["Return OrderDTO"]
        Leak["LEAK: conn.close() NEVER called!"]
    end

    subgraph HikariCP ["HikariPool-1 (maximumPoolSize = 10)"]
        Active["Active Connections: 10/10 (Pinned)"]
        Queue["Wait Queue: 84 Threads Blocked (30,000ms max)"]
    end

    subgraph Failure ["Systemic Impact"]
        Timeout["SQLTransientConnectionException"]
        Collapse["Throughput collapses to 1.8 TPS"]
        SLA["P99 Latency explodes to 3,450ms"]
    end

    Req1 & Req2 --> Acq
    Acq --> Query --> Return
    Return -.-> Leak
    Leak --> Active
    ReqN --> Acq
    Acq -.->|No idle connections| Queue
    Queue -->|30s timeout expired| Timeout
    Timeout --> Collapse & SLA
```

### Mathematical & Queuing Theory Breakdown

Under Little's Law:

$$L = \lambda W$$

Where:
* $L$ is the average number of requests in the system.
* $\lambda$ is the arrival rate ($\approx 45.2\text{ requests/sec}$).
* $W$ is the average response time.

When the connection pool size $C = 10$ is completely leased and never released, the service rate $\mu$ of the pool drops to zero for any new connection. Any incoming request must wait for the maximum connection timeout:

$$W_{\text{wait}} = 30,000\text{ ms} = 30\text{ seconds}$$

With $\lambda = 45.2\text{ req/sec}$ and $W = 30\text{ s}$, the queue backlog $L$ theoretically demands:

$$L_{\text{theoretical}} = 45.2 \times 30 = 1,356\text{ queued threads}$$

Because the web container worker thread pool had a maximum cap of approximately 100 threads, **84 worker threads** were instantly trapped in HikariCP's lock-acquisition queue. This induced **head-of-line blocking**, starving CPU and network threads from handling unrelated API endpoints.

---

## 4. Root Cause Analysis (The 5 Whys)

| Level | Diagnostic Question | Forensic Finding |
| :--- | :--- | :--- |
| **Why 1** | Why did checkout and order detail lookups time out after 30 seconds with HTTP 504 errors? | The database connection pool `HikariPool-1` timed out trying to lease an available database connection. |
| **Why 2** | Why was `HikariPool-1` unable to lease any connection? | All 10 connections in `maximumPoolSize` were permanently pinned in an `active` state with zero idle connections. |
| **Why 3** | Why were the active connections never released back to the pool? | `OrderService.getOrderDetailsFast()` obtained a JDBC `Connection` via `dataSource.getConnection()` but never called `close()` or used `try-with-resources`. |
| **Why 4** | Why did the code use unmanaged raw JDBC instead of the established Spring Data / Hibernate repository? | Commit `b8f3a9e` attempted a micro-optimization to bypass ORM reflection overhead for fast-path order reads. |
| **Why 5** | Why did this defect reach production without detection? | Unit tests mocked the `DataSource` without verifying closure semantics, and the CI pipeline lacked static analysis rules (`squid:S2095`) and concurrency stress testing. |

---

## 5. Culprit Git Commit & try-with-resources Patch

### Culprit Git Commit
* **Commit Hash**: `b8f3a9e`
* **Author**: Alex Dev `<alex.dev@acme-commerce.com>`
* **Commit Subject**: `feat(order): bypass ORM reflection with direct JDBC fast-path lookup`
* **File**: `OrderService.java` (Line 41)
* **Defect Classification**: Connection Resource Leak (`CWE-772`)
* **Matched Incident**: `OPP-3716` (98.4% Vector Overlap)

### Verified Patch (Staged PR: `fix/PERF-512-order-service-try-with-resources`)

```diff
@@ src/main/java/com/enterprise/order/service/OrderService.java @@
- Connection conn = dataSource.getConnection(); // [LEAK: Never closed!]
- PreparedStatement stmt = conn.prepareStatement("SELECT * FROM orders WHERE id = ?");
+ try (Connection conn = dataSource.getConnection();
+      PreparedStatement stmt = conn.prepareStatement("SELECT * FROM orders WHERE id = ?")) {
+     stmt.setString(1, orderId);
+     try (ResultSet rs = stmt.executeQuery()) {
          if (rs.next()) {
              return new OrderDTO(...);
          }
+     }
+ } // AutoCloseable guarantees connection is returned to Hikari pool!
```

> [!NOTE]
> In HikariCP, calling `.close()` on a connection proxy does not close the physical database TCP socket. Instead, `HikariProxyConnection.close()` intercepts the call and returns the physical connection to the idle pool bag in sub-microsecond time.

### Automated Verification Test Suite

* **Verification Test**: `OrderServicePoolExhaustionTest`
* **Test Parameters**: 100 parallel worker threads, 2,000 sustained queries against a 10-connection pool.
* **Test Status**: **✔ PASSED**
* **Verification Metrics**:
  * Leaked Connections: **0**
  * Maximum Pool Wait Time: **2.1 ms** (vs. 30,000 ms pre-fix)
  * Average Query Time: **3.8 ms**
  * Acquisition Timeout Errors: **0 (0.00%)**

---

## 6. Corrective and Preventive Actions (CAPA)

```mermaid
flowchart LR
    A["Immediate Hotfix (P0)"] --> B["Connection Pool Tuning (P0)"]
    B --> C["Leak Detection Threshold (P1)"]
    C --> D["Static Analysis in CI (P1)"]
    D --> E["Load Testing Pipeline (P2)"]
```

| ID | Action Item | Priority | Target Date | Owner | Verification Gate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **ACT-01** | Merge staged PR `fix/PERF-512-order-service-try-with-resources` and deploy patch release `v2.14.1`. | **P0** | Immediate | Alex Dev / DevOps | Canaries green; 0 pool timeouts |
| **ACT-02** | Adjust pool sizing in `application.yml`: increase `maximumPoolSize` from 10 to 25 and `minimumIdle` to 10. | **P0** | Day 1 | SRE / Database Lead | Pool headroom > 50% under 50 TPS |
| **ACT-03** | Enable HikariCP `leakDetectionThreshold = 5000` (5s) to trigger automated stack trace logging if a connection is leased > 5s. | **P1** | Day 2 | Backend Infra | Log alert on unclosed connection |
| **ACT-04** | Enforce SonarQube / ErrorProne check `squid:S2095` ("Resources should be closed") as a blocking PR check in CI. | **P1** | Day 3 | Platform QA | PRs fail on unclosed `AutoCloseable` |
| **ACT-05** | Add `OrderServicePoolExhaustionTest` (100 parallel workers) to nightly performance regression testing. | **P2** | Day 7 | QA Automation | Automated pass criteria in pipeline |
| **ACT-06** | Deploy Resilience4j Circuit Breaker on all database client paths with a 2-second timeout fallback. | **P2** | Sprint 44 | Order SRE | Prevents thread pool starvation |

---

## 7. Sign-off & Approvals

| Approver Role | Designated Stakeholder | Status | Timestamp |
| :--- | :--- | :--- | :--- |
| **Incident Commander** | Lead SRE | **APPROVED** | 2026-10-27 16:30 UTC |
| **Service Owner** | Principal Architect (`order-service`) | **APPROVED** | 2026-10-27 16:35 UTC |
| **Culprit Commit Author** | Alex Dev | **CONFIRMED & FIXED** | 2026-10-27 16:40 UTC |
| **Verification Gate** | PerfRCA Agent Autonomous Test Runner | **VERIFIED (100 Threads)** | 2026-10-27 16:42 UTC |
