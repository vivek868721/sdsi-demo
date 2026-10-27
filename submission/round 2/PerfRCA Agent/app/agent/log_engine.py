"""
High-throughput Log Clustering & Pattern Extraction Engine for PerfRCA Agent.
Simulates and clusters 45,000+ log lines into concise semantic templates (similar to Drain / LogPai algorithms).
"""

import time
import random
from typing import List, Dict, Any

NORMAL_LOG_TEMPLATES = [
    "[INFO]  [HikariPool-1] Pool stats (total=10, active=2, idle=8, waiting=0)",
    "[DEBUG] [org.springframework.jdbc.core.JdbcTemplate] Executing SQL query [SELECT * FROM orders WHERE id = ?]",
    "[INFO]  [com.enterprise.order.service.OrderService] Order lookup succeeded for id: ORD-{uuid}",
    "[DEBUG] [org.postgresql.jdbc.PgConnection] Transaction committed successfully in 14ms",
    "[INFO]  [com.enterprise.order.controller.OrderController] HTTP GET /api/v1/orders/{uuid} 200 OK (16ms)"
]

LEAK_LOG_TEMPLATES = [
    "[ERROR] [HikariPool-1] Connection is not available, request timed out after 30000ms (total=10, active=10, idle=0, waiting={waiting_threads})",
    "[ERROR] [org.springframework.dao.CannotAcquireLockException] Could not get JDBC Connection; nested exception is java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 30000ms",
    "[WARN]  [com.zaxxer.hikari.pool.PoolBase] HikariPool-1 - Failed to validate connection org.postgresql.jdbc.PgConnection (timeout after 5000ms)",
    "[ERROR] [com.enterprise.order.service.OrderService] Connection leak detected: thread {thread_id} acquired connection in getOrderDetailsFast() at line 84 without release",
    "[ERROR] [org.apache.coyote.http11.Http11NioProtocol] Error processing request on thread [{thread_id}] - DB pool starvation"
]

CLUSTERING_RESULTS = {
    "total_logs_analyzed": 45000,
    "time_window": "Last 15 minutes (T-15m to T-0m)",
    "clustering_algorithm": "Drain-Tree Semantic Template Miner (Depth=4, SimThreshold=0.85)",
    "unique_templates_found": 4,
    "anomalous_ratio": "98.8%",
    "clusters": [
        {
            "cluster_id": "CLUSTER-01",
            "count": 39812,
            "percentage": 88.47,
            "severity": "CRITICAL",
            "template": "[HikariPool-1] Connection is not available, request timed out after <NUM>ms (total=10, active=10, idle=0, waiting=<NUM>)",
            "sample_log": "2026-10-27T10:18:42.109Z ERROR [HikariPool-1] Connection is not available, request timed out after 30000ms (total=10, active=10, idle=0, waiting=84)",
            "signature": "POOL_TIMEOUT_EXHAUSTION",
            "variables_identified": ["timeout_ms", "waiting_threads"]
        },
        {
            "cluster_id": "CLUSTER-02",
            "count": 4110,
            "percentage": 9.13,
            "severity": "CRITICAL",
            "template": "org.springframework.dao.CannotAcquireLockException: Could not get JDBC Connection; nested exception is java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available",
            "sample_log": "2026-10-27T10:18:43.002Z ERROR [org.springframework.dao.CannotAcquireLockException] Could not get JDBC Connection; nested exception is java.sql.SQLTransientConnectionException",
            "signature": "SPRING_JDBC_TRANSIENT_FAILURE",
            "variables_identified": []
        },
        {
            "cluster_id": "CLUSTER-03",
            "count": 786,
            "percentage": 1.75,
            "severity": "HIGH",
            "template": "com.enterprise.order.service.OrderService: Thread <THREAD_ID> acquired connection in getOrderDetailsFast() without release",
            "sample_log": "2026-10-27T10:17:15.894Z WARN [com.enterprise.order.service.OrderService] Thread http-nio-8080-exec-14 acquired connection in getOrderDetailsFast() without release",
            "signature": "UNCLOSED_CONNECTION_ORIGIN",
            "variables_identified": ["thread_id"]
        },
        {
            "cluster_id": "CLUSTER-04",
            "count": 292,
            "percentage": 0.65,
            "severity": "HIGH",
            "template": "org.postgresql.util.PSQLException: FATAL: remaining connection slots are reserved for non-replication superuser connections",
            "sample_log": "2026-10-27T10:19:01.321Z ERROR [org.postgresql.util.PSQLException] FATAL: remaining connection slots are reserved",
            "signature": "PG_BACKEND_SATURATION",
            "variables_identified": []
        }
    ],
    "deduced_primary_failure_pattern": (
        "HikariCP connection pool saturated at 10/10 active leases. Incoming requests queue up waiting for connections, "
        "timing out after 30000ms. Root call site identified at `OrderService.getOrderDetailsFast()`."
    )
}

class LogEngine:
    """Simulates real-time application logs and delivers clustered pattern mining."""

    @staticmethod
    def get_cluster_analysis() -> Dict[str, Any]:
        return CLUSTERING_RESULTS

    @staticmethod
    def generate_live_log(mode: str, waiting_threads: int = 0) -> str:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}Z"
        if mode == "leak":
            template = random.choice(LEAK_LOG_TEMPLATES)
            log_str = template.format(
                waiting_threads=max(12, waiting_threads),
                thread_id=f"http-nio-8080-exec-{random.randint(1, 64)}"
            )
            return f"{timestamp} {log_str}"
        else:
            template = random.choice(NORMAL_LOG_TEMPLATES)
            log_str = template.format(
                uuid=f"{random.randint(100000, 999999)}"
            )
            return f"{timestamp} {log_str}"
