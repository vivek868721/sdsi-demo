"""
Real-time DB Telemetry & Prometheus Metric Exporter for PerfRCA Agent.
Maintains live time-series data for Connection Pool Saturation, P50/P90/P99 Latency, and Throughput (TPS).
"""

import time
import random
import asyncio
from typing import Dict, Any, List
from prometheus_client import Gauge, Counter, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST

from app.agent.log_engine import LogEngine

# Custom Prometheus Registry
REGISTRY = CollectorRegistry()

# Prometheus Metric Definitions
PROM_POOL_ACTIVE = Gauge("db_connection_pool_active_connections", "Active leased connections in DB pool", ["pool"], registry=REGISTRY)
PROM_POOL_MAX = Gauge("db_connection_pool_max_connections", "Maximum capacity of DB connection pool", ["pool"], registry=REGISTRY)
PROM_WAITING_THREADS = Gauge("db_connection_pool_waiting_threads", "Threads queued waiting for a DB connection", ["pool"], registry=REGISTRY)
PROM_LATENCY_P50 = Gauge("db_query_latency_p50_milliseconds", "P50 Query Latency in milliseconds", registry=REGISTRY)
PROM_LATENCY_P90 = Gauge("db_query_latency_p90_milliseconds", "P90 Query Latency in milliseconds", registry=REGISTRY)
PROM_LATENCY_P99 = Gauge("db_query_latency_p99_milliseconds", "P99 Query Latency in milliseconds", registry=REGISTRY)
PROM_THROUGHPUT_TPS = Gauge("db_query_throughput_tps", "Database queries processed per second (TPS)", registry=REGISTRY)
PROM_TIMEOUTS_TOTAL = Counter("db_query_timeouts_total", "Total database connection acquisition timeouts", registry=REGISTRY)
PROM_AGENT_STEP = Gauge("rca_agent_step", "Current execution step of PerfRCA Agent (0=Idle, 1-5=Active Stages)", registry=REGISTRY)

# Subsystem Prometheus Gauges
PROM_APP_CPU = Gauge("app_server_cpu_utilization_percent", "Application Server CPU Utilization (%)", registry=REGISTRY)
PROM_APP_HEAP = Gauge("app_server_jvm_heap_used_bytes", "Application Server JVM Heap Used (bytes)", registry=REGISTRY)
PROM_DB_CPU = Gauge("db_server_cpu_utilization_percent", "Database Server CPU Utilization (%)", registry=REGISTRY)
PROM_DB_RAM = Gauge("db_server_memory_used_bytes", "Database Server RAM Used (bytes)", registry=REGISTRY)


class TelemetryEngine:
    """Simulates real-time telemetry and synchronizes with Prometheus metrics."""

    def __init__(self):
        self.mode = "normal"  # "normal", "leak", "investigating", "resolved"
        self.max_pool_size = 10
        self.active_connections = 2.0
        self.waiting_threads = 0
        self.latency_p50 = 12.0
        self.latency_p90 = 15.0
        self.latency_p99 = 16.5
        self.throughput_tps = 45.2
        self.timeout_count = 0
        self.agent_step = 0

        # Subsystem Metrics
        self.app_cpu_percent = 23.5
        self.app_blocked_threads = 0
        self.app_heap_used_mb = 1450.0
        self.app_gc_pause_ms = 12.0
        self.db_cpu_percent = 18.2
        self.db_active_backends = 10
        self.db_ram_used_gb = 6.7
        self.db_cache_hit_pct = 99.4

        self.history: List[Dict[str, Any]] = []
        self.recent_logs: List[str] = []
        self.max_history = 40
        self.max_logs = 100

        # Pre-populate history with 25 seconds of healthy, dynamic baseline with realistic random consumption
        start_time = time.time() - 25
        curr_app_cpu = 23.5
        curr_heap = 1380.0
        curr_gc = 12.0
        curr_db_cpu = 18.2
        curr_backends = 10
        curr_ram = 6.6
        curr_cache = 99.4

        for i in range(25):
            t = start_time + i
            # Realistic wave for App CPU
            curr_app_cpu = max(19.0, min(36.0, curr_app_cpu + random.uniform(-3.5, 3.8) + (25.0 - curr_app_cpu) * 0.15))
            
            # JVM Heap sawtooth memory allocation & GC
            curr_heap += random.uniform(25.0, 55.0)
            if curr_heap > 1680.0:
                curr_heap = random.uniform(1320.0, 1390.0)
                curr_gc = random.uniform(20.0, 32.0)
            else:
                curr_gc = max(6.0, min(16.0, curr_gc + random.uniform(-1.5, 1.8)))

            # PostgreSQL Host CPU & Backends wave
            curr_db_cpu = max(13.5, min(29.0, curr_db_cpu + random.uniform(-2.8, 3.0) + (18.5 - curr_db_cpu) * 0.18))
            curr_backends = max(8, min(14, curr_backends + random.choice([-1, 0, 1])))
            curr_ram = max(6.3, min(7.2, curr_ram + random.uniform(-0.1, 0.12)))
            curr_cache = max(98.6, min(99.8, curr_cache + random.uniform(-0.18, 0.18)))

            self.history.append({
                "time": time.strftime("%H:%M:%S", time.localtime(t)),
                "active_connections": round(2 + random.uniform(-0.3, 0.4), 1),
                "max_connections": 10,
                "latency_p50": round(12.0 + random.uniform(-1.0, 1.5), 1),
                "latency_p90": round(14.5 + random.uniform(-1.0, 1.8), 1),
                "latency_p99": round(16.0 + random.uniform(-1.0, 2.0), 1),
                "throughput_tps": round(45.0 + random.uniform(-2.5, 3.0), 1),
                "waiting_threads": 0,
                "app_cpu_percent": round(curr_app_cpu, 1),
                "app_blocked_threads": 0,
                "app_heap_used_mb": round(curr_heap, 1),
                "app_gc_pause_ms": round(curr_gc, 1),
                "db_cpu_percent": round(curr_db_cpu, 1),
                "db_active_backends": curr_backends,
                "db_ram_used_gb": round(curr_ram, 1),
                "db_cache_hit_pct": round(curr_cache, 1)
            })

    def set_mode(self, new_mode: str):
        self.mode = new_mode

    def set_agent_step(self, step: int):
        self.agent_step = step
        PROM_AGENT_STEP.set(step)

    def tick(self):
        """Simulate single telemetry tick (called every 1s)."""
        now = time.time()
        time_label = time.strftime("%H:%M:%S", time.localtime(now))

        if self.mode == "normal" or self.mode == "resolved":
            # Gracefully converge to healthy baseline
            target_active = 2.0 + random.uniform(-0.3, 0.4)
            self.active_connections += (target_active - self.active_connections) * 0.4
            self.active_connections = max(1.0, min(3.0, self.active_connections))
            self.waiting_threads = 0

            target_p50 = 12.0 + random.uniform(-1.0, 1.2)
            target_p90 = 14.5 + random.uniform(-1.0, 1.5)
            target_p99 = 16.0 + random.uniform(-1.0, 2.0)
            self.latency_p50 += (target_p50 - self.latency_p50) * 0.4
            self.latency_p90 += (target_p90 - self.latency_p90) * 0.4
            self.latency_p99 += (target_p99 - self.latency_p99) * 0.4

            target_tps = 45.2 + random.uniform(-2.5, 3.0)
            self.throughput_tps += (target_tps - self.throughput_tps) * 0.4

            # Subsystem Dynamic Random Consumption (App Server CPU fluctuating ~19% - 36%)
            cpu_wander = random.uniform(-4.2, 4.2)
            cpu_restoring = (24.5 - self.app_cpu_percent) * 0.18
            self.app_cpu_percent = max(18.5, min(38.0, self.app_cpu_percent + cpu_wander + cpu_restoring))
            self.app_blocked_threads = 0

            # Authentic JVM Heap Allocation & Minor GC Sawtooth Pattern
            self.app_heap_used_mb += random.uniform(25.0, 60.0)
            if self.app_heap_used_mb > random.uniform(1650.0, 1850.0):
                # Young-gen GC kicks in: drops memory back down to ~1280 - 1380 MB
                self.app_heap_used_mb = random.uniform(1280.0, 1380.0)
                self.app_gc_pause_ms = random.uniform(18.0, 32.0)
            else:
                self.app_gc_pause_ms = max(6.0, min(16.0, self.app_gc_pause_ms + random.uniform(-1.8, 1.8)))

            # PostgreSQL Host CPU Dynamic Consumption (fluctuating ~13% - 29%)
            db_cpu_wander = random.uniform(-3.2, 3.5)
            db_restoring = (18.2 - self.db_cpu_percent) * 0.2
            self.db_cpu_percent = max(13.0, min(32.0, self.db_cpu_percent + db_cpu_wander + db_restoring))

            # PostgreSQL active backend connection jitter (8 - 14 active clients)
            self.db_active_backends = max(7, min(15, self.db_active_backends + random.choice([-1, 0, 0, 1])))

            # PostgreSQL Host RAM & Cache Hit dynamic consumption
            self.db_ram_used_gb = max(6.2, min(7.5, self.db_ram_used_gb + random.uniform(-0.12, 0.14)))
            self.db_cache_hit_pct = max(98.5, min(99.9, self.db_cache_hit_pct + random.uniform(-0.25, 0.25)))

        elif self.mode in ("leak", "investigating"):
            # Surge to saturated state
            self.active_connections = min(10.0, self.active_connections + random.uniform(1.2, 2.5))
            self.waiting_threads = min(96, self.waiting_threads + random.randint(4, 12))

            # Latency surges >3000ms
            target_p50 = 1850.0 + random.uniform(100.0, 300.0)
            target_p90 = 2950.0 + random.uniform(150.0, 350.0)
            target_p99 = 3450.0 + random.uniform(200.0, 500.0)
            self.latency_p50 += (target_p50 - self.latency_p50) * 0.5
            self.latency_p90 += (target_p90 - self.latency_p90) * 0.5
            self.latency_p99 += (target_p99 - self.latency_p99) * 0.5

            # TPS plummets down to ~1.8
            target_tps = 1.8 + random.uniform(-0.6, 0.8)
            self.throughput_tps += (target_tps - self.throughput_tps) * 0.5
            self.throughput_tps = max(0.5, self.throughput_tps)

            # Subsystem Leak Spikes - high consumption and heavy fluctuation
            self.app_cpu_percent = min(98.5, self.app_cpu_percent + random.uniform(4.5, 9.0))
            self.app_blocked_threads = self.waiting_threads
            self.app_heap_used_mb = min(3850.0, self.app_heap_used_mb + random.uniform(130.0, 240.0))
            self.app_gc_pause_ms = min(680.0, self.app_gc_pause_ms + random.uniform(25.0, 55.0))
            self.db_cpu_percent = min(88.0, self.db_cpu_percent + random.uniform(3.5, 7.5))
            self.db_active_backends = min(100, self.db_active_backends + random.randint(6, 14))
            self.db_ram_used_gb = min(15.2, self.db_ram_used_gb + random.uniform(0.5, 1.1))
            self.db_cache_hit_pct = max(70.0, self.db_cache_hit_pct - random.uniform(1.2, 3.0))

            # Timeouts increment
            self.timeout_count += random.randint(15, 35)
            PROM_TIMEOUTS_TOTAL.inc(random.randint(15, 35))

        # Update Prometheus Gauges
        PROM_POOL_ACTIVE.labels(pool="HikariPool-1").set(round(self.active_connections, 1))
        PROM_POOL_MAX.labels(pool="HikariPool-1").set(self.max_pool_size)
        PROM_WAITING_THREADS.labels(pool="HikariPool-1").set(self.waiting_threads)
        PROM_LATENCY_P50.set(round(self.latency_p50, 1))
        PROM_LATENCY_P90.set(round(self.latency_p90, 1))
        PROM_LATENCY_P99.set(round(self.latency_p99, 1))
        PROM_THROUGHPUT_TPS.set(round(self.throughput_tps, 1))

        # Subsystem Prometheus Gauges
        PROM_APP_CPU.set(round(self.app_cpu_percent, 1))
        PROM_APP_HEAP.set(int(self.app_heap_used_mb * 1024 * 1024))
        PROM_DB_CPU.set(round(self.db_cpu_percent, 1))
        PROM_DB_RAM.set(int(self.db_ram_used_gb * 1024 * 1024 * 1024))

        # Update Live History
        data_point = {
            "time": time_label,
            "active_connections": round(self.active_connections, 1),
            "max_connections": self.max_pool_size,
            "latency_p50": round(self.latency_p50, 1),
            "latency_p90": round(self.latency_p90, 1),
            "latency_p99": round(self.latency_p99, 1),
            "throughput_tps": round(self.throughput_tps, 1),
            "waiting_threads": self.waiting_threads,
            "app_cpu_percent": round(self.app_cpu_percent, 1),
            "app_blocked_threads": self.app_blocked_threads,
            "app_heap_used_mb": round(self.app_heap_used_mb, 1),
            "app_gc_pause_ms": round(self.app_gc_pause_ms, 1),
            "db_cpu_percent": round(self.db_cpu_percent, 1),
            "db_active_backends": self.db_active_backends,
            "db_ram_used_gb": round(self.db_ram_used_gb, 1),
            "db_cache_hit_pct": round(self.db_cache_hit_pct, 1)
        }
        self.history.append(data_point)
        if len(self.history) > self.max_history:
            self.history.pop(0)

        # Generate live log
        new_log = LogEngine.generate_live_log(self.mode, self.waiting_threads)
        self.recent_logs.append(new_log)
        if len(self.recent_logs) > self.max_logs:
            self.recent_logs.pop(0)

    def get_current_metrics(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "active_connections": round(self.active_connections, 1),
            "max_connections": self.max_pool_size,
            "pool_utilization_pct": round((self.active_connections / self.max_pool_size) * 100, 1),
            "waiting_threads": self.waiting_threads,
            "latency_p50_ms": round(self.latency_p50, 1),
            "latency_p90_ms": round(self.latency_p90, 1),
            "latency_p99_ms": round(self.latency_p99, 1),
            "throughput_tps": round(self.throughput_tps, 1),
            "timeout_count": self.timeout_count,
            "agent_step": self.agent_step,
            "subsystems": {
                "app_cpu": {
                    "percent": round(self.app_cpu_percent, 1),
                    "blocked_threads": self.app_blocked_threads,
                    "load_avg": round(1.2 if self.mode == "normal" else 7.8, 2),
                    "vcpus": 8,
                    "status": "CRITICAL" if self.app_cpu_percent > 75 else "HEALTHY"
                },
                "app_memory": {
                    "heap_used_mb": round(self.app_heap_used_mb, 1),
                    "heap_max_mb": 4096.0,
                    "heap_util_pct": round((self.app_heap_used_mb / 4096.0) * 100, 1),
                    "gc_pause_ms": round(self.app_gc_pause_ms, 1),
                    "metaspace_mb": 84.0,
                    "status": "WARNING" if self.app_heap_used_mb > 3000 else "HEALTHY"
                },
                "db_cpu": {
                    "percent": round(self.db_cpu_percent, 1),
                    "active_backends": self.db_active_backends,
                    "max_backends": 100,
                    "iowait_pct": round(1.5 if self.mode == "normal" else 8.4, 1),
                    "status": "WARNING" if self.db_cpu_percent > 70 else "HEALTHY"
                },
                "db_memory": {
                    "ram_used_gb": round(self.db_ram_used_gb, 1),
                    "ram_total_gb": 16.0,
                    "ram_util_pct": round((self.db_ram_used_gb / 16.0) * 100, 1),
                    "cache_hit_pct": round(self.db_cache_hit_pct, 1),
                    "shared_buffers_gb": 4.2 if self.mode == "normal" else 7.6,
                    "status": "WARNING" if self.db_ram_used_gb > 12.0 else "HEALTHY"
                }
            },
            "history": self.history,
            "recent_logs": self.recent_logs[-15:]
        }

    def get_prometheus_metrics(self) -> str:
        return generate_latest(REGISTRY).decode("utf-8")


telemetry_engine = TelemetryEngine()
