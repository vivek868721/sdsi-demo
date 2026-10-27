"""
FastAPI Backend Server for PerfRCA Agent.
Exposes Prometheus /metrics, Live Telemetry API, SSE Agent Trace Stream, and Interactive Controls.
"""

import os
import json
import asyncio
from typing import Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST

from app.telemetry import telemetry_engine
from app.agent.state_machine import PerfRCAStateMachine
from app.agent.memory import HISTORICAL_INCIDENTS
from app.agent.code_repo import CodeRepoEngine
from app.agent.log_engine import LogEngine

state_machine = PerfRCAStateMachine(telemetry_engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Background telemetry generator loop running every 1s."""
    async def ticker():
        while True:
            try:
                telemetry_engine.tick()
            except Exception as e:
                print(f"[Telemetry Ticker Error] {e}")
            await asyncio.sleep(1.0)

    task = asyncio.create_task(ticker())
    yield
    task.cancel()


app = FastAPI(
    title="PerfRCA Agent - Autonomous Performance Root Cause Analysis",
    description="Live Dashboard, Prometheus Metrics, and Multi-Stage RCA Agent",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure app/static directory exists
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the complete self-contained HTML/CSS/Chart.js dashboard."""
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>PerfRCA Agent: index.html not found</h1>", status_code=404)


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint conforming to Prometheus scrapers."""
    content = telemetry_engine.get_prometheus_metrics()
    return Response(content=content, media_type=CONTENT_TYPE_LATEST)


@app.get("/api/metrics")
async def get_live_metrics():
    """Real-time JSON metrics endpoint for UI charts & gauges."""
    return JSONResponse(content=telemetry_engine.get_current_metrics())


@app.post("/api/control/normal")
async def control_normal():
    """Sets simulation load to Normal operations (pool ~2/10, latency ~15ms, TPS ~45)."""
    telemetry_engine.set_mode("normal")
    telemetry_engine.set_agent_step(0)
    return JSONResponse(content={
        "status": "OK",
        "mode": "normal",
        "message": "Normal operational load initiated. Pool usage low (~2/10), latency ~15ms, TPS ~45."
    })


@app.post("/api/control/leak")
async def control_leak():
    """Injects Connection Leak regression (pool maxes out at 10/10, latency >3000ms, TPS plummets)."""
    telemetry_engine.set_mode("leak")
    return JSONResponse(content={
        "status": "OK",
        "mode": "leak",
        "message": "Connection leak injected! Pool saturating to 10/10, latency surging >3000ms, TPS plummeting."
    })


@app.post("/api/control/apply-fix")
async def control_apply_fix():
    """Applies verified try-with-resources patch and drains pool back to healthy baseline."""
    res = state_machine.apply_fix()
    return JSONResponse(content=res)


@app.get("/api/agent/stream")
async def stream_agent_investigation(request: Request):
    """
    Server-Sent Events (SSE) streaming the live 5-step agent state-machine execution.
    """
    async def event_generator():
        async for event in state_machine.run_investigation():
            if await request.is_disconnected():
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/api/incident/opp-3716")
async def get_incident_opp3716():
    """Returns institutional memory details for historical incident OPP-3716."""
    opp3716 = next((inc for inc in HISTORICAL_INCIDENTS if inc["incident_id"] == "OPP-3716"), None)
    return JSONResponse(content=opp3716 or {})


@app.get("/api/commit/b8f3a9e")
async def get_commit_b8f3a9e():
    """Returns Git commit details and unified diff for commit b8f3a9e."""
    return JSONResponse(content={
        "commit": CodeRepoEngine.get_commit_b8f3a9e(),
        "unified_diff": CodeRepoEngine.get_unified_diff(),
        "jira_ticket": CodeRepoEngine.generate_jira_ticket()
    })


@app.get("/api/cluster/analysis")
async def get_cluster_analysis():
    """Returns the 45,000 log clustering analysis."""
    return JSONResponse(content=LogEngine.get_cluster_analysis())


@app.get("/api/report/download")
async def download_rca_report():
    """Generates and downloads the comprehensive Incident RCA Word (.doc) Report."""
    report_doc = state_machine.generate_incident_report_doc()
    filename = "PerfRCA_Incident_Report_PERF-512.doc"
    doc_bytes = report_doc.encode("utf-8")
    return Response(
        content=doc_bytes,
        media_type="application/msword",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/msword; charset=utf-8",
            "Content-Length": str(len(doc_bytes)),
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )


class GrafanaInspectRequest(BaseModel):
    url: str = "http://grafana.internal:3000/d/perf-prod/hikari-postgres-pool"
    view: str = "grafana"  # Options: "grafana", "app_cpu", "app_memory", "db_cpu", "db_memory"


@app.post("/api/grafana/inspect")
async def inspect_grafana(request: GrafanaInspectRequest):
    """
    Inspects a target Grafana dashboard URL and returns tailored telemetry panels
    for the selected subsystem view (Grafana Overview, App CPU, App Memory, DB CPU, DB Memory).
    """
    url = request.url.strip() if request.url else "http://grafana.internal:3000/d/perf-prod/hikari-postgres-pool"
    state_machine.set_grafana_url(url)
    view = (request.view or "grafana").lower().strip()
    
    metrics = telemetry_engine.get_current_metrics()
    is_leak = metrics["mode"] in ("leak", "investigating")
    subsystems = metrics.get("subsystems", {})
    app_cpu = subsystems.get("app_cpu", {})
    app_mem = subsystems.get("app_memory", {})
    db_cpu = subsystems.get("db_cpu", {})
    db_mem = subsystems.get("db_memory", {})

    # Build telemetry panels and titles per user dropdown selection
    if view == "app_cpu":
        title = "Application Server Cluster — CPU & Thread Telemetry"
        uid = "app-server-cpu"
        alert_name = "AppServerThreadStarvation" if is_leak else "AppServerCPUWithinSLA"
        panels = [
            {
                "id": 1,
                "title": "App Server CPU Utilization",
                "type": "gauge",
                "promql": 'rate(node_cpu_seconds_total{instance="app-01", mode!="idle"}[1m]) * 100',
                "current_value": f"{app_cpu.get('percent', 23.5)}%",
                "status": "CRITICAL" if is_leak else "NORMAL"
            },
            {
                "id": 2,
                "title": "Worker Threads Blocked / Waiting",
                "type": "stat",
                "promql": 'jvm_threads_state{state="blocked"}',
                "current_value": f"{app_cpu.get('blocked_threads', 0)} threads blocked",
                "status": "CRITICAL" if is_leak else "NORMAL"
            },
            {
                "id": 3,
                "title": "OS Load Average (1m)",
                "type": "timeseries",
                "promql": 'node_load1{instance="app-01"}',
                "current_value": f"{app_cpu.get('load_avg', 1.2)} (8 vCPUs)",
                "status": "DEGRADED" if is_leak else "NORMAL"
            },
            {
                "id": 4,
                "title": "System Context Switches",
                "type": "timeseries",
                "promql": 'rate(node_context_switches_total{instance="app-01"}[1m])',
                "current_value": "46,200/s (Lock Spinning)" if is_leak else "3,400/s (Normal)",
                "status": "CRITICAL" if is_leak else "NORMAL"
            }
        ]
    elif view == "app_memory":
        title = "Application Server Cluster — JVM Heap & Garbage Collection"
        uid = "app-server-memory"
        alert_name = "JVMHeapNearExhaustion" if is_leak else "JVMHeapHealthy"
        panels = [
            {
                "id": 1,
                "title": "JVM Heap Memory Used",
                "type": "gauge",
                "promql": 'jvm_memory_used_bytes{area="heap"} / jvm_memory_max_bytes * 100',
                "current_value": f"{app_mem.get('heap_used_mb', 1450)} MB / 4096 MB ({app_mem.get('heap_util_pct', 35.4)}%)",
                "status": "WARNING" if is_leak else "NORMAL"
            },
            {
                "id": 2,
                "title": "GC Pause Latency (Stop-the-World)",
                "type": "timeseries",
                "promql": 'jvm_gc_pause_seconds_sum * 1000',
                "current_value": f"{app_mem.get('gc_pause_ms', 12)} ms",
                "status": "CRITICAL" if is_leak else "NORMAL"
            },
            {
                "id": 3,
                "title": "Metaspace Allocation",
                "type": "stat",
                "promql": 'jvm_memory_used_bytes{area="nonheap", id="Metaspace"}',
                "current_value": f"{app_mem.get('metaspace_mb', 84)} MB / 256 MB",
                "status": "NORMAL"
            },
            {
                "id": 4,
                "title": "GC Memory Allocation Rate",
                "type": "timeseries",
                "promql": 'rate(jvm_gc_memory_allocated_bytes_total[1m])',
                "current_value": "320 MB/s (High Retained Handles)" if is_leak else "45 MB/s (Optimal)",
                "status": "WARNING" if is_leak else "NORMAL"
            }
        ]
    elif view == "db_cpu":
        title = "PostgreSQL Database Server Host — CPU & Process Load"
        uid = "db-server-cpu"
        alert_name = "PostgresBackendSaturation" if is_leak else "PostgresCPUHealthy"
        panels = [
            {
                "id": 1,
                "title": "PostgreSQL Host CPU Utilization",
                "type": "gauge",
                "promql": 'rate(node_cpu_seconds_total{instance="postgres-01", mode!="idle"}[1m]) * 100',
                "current_value": f"{db_cpu.get('percent', 18.2)}%",
                "status": "WARNING" if is_leak else "NORMAL"
            },
            {
                "id": 2,
                "title": "PostgreSQL Active Backend Processes",
                "type": "stat",
                "promql": 'pg_stat_activity_count{state="active"}',
                "current_value": f"{db_cpu.get('active_backends', 10)} / 100 (Max: 100)",
                "status": "CRITICAL" if is_leak else "NORMAL"
            },
            {
                "id": 3,
                "title": "CPU IO-Wait Time",
                "type": "timeseries",
                "promql": 'rate(node_cpu_seconds_total{mode="iowait"}[1m]) * 100',
                "current_value": f"{db_cpu.get('iowait_pct', 1.5)}%",
                "status": "DEGRADED" if is_leak else "NORMAL"
            },
            {
                "id": 4,
                "title": "Transaction Lock Waiters",
                "type": "stat",
                "promql": 'pg_locks_waiting_total',
                "current_value": f"{metrics['waiting_threads']} lock waiters" if is_leak else "0 lock waiters",
                "status": "CRITICAL" if is_leak else "NORMAL"
            }
        ]
    elif view == "db_memory":
        title = "PostgreSQL Database Server Host — RAM & Shared Buffers"
        uid = "db-server-memory"
        alert_name = "PostgresRAMHighWatermark" if is_leak else "PostgresRAMHealthy"
        panels = [
            {
                "id": 1,
                "title": "Database Host RAM Utilization",
                "type": "gauge",
                "promql": '(node_memory_MemTotal - node_memory_MemAvailable) / MemTotal * 100',
                "current_value": f"{db_mem.get('ram_used_gb', 6.7)} GB / 16.0 GB ({db_mem.get('ram_util_pct', 41.8)}%)",
                "status": "WARNING" if is_leak else "NORMAL"
            },
            {
                "id": 2,
                "title": "PostgreSQL Buffer Cache Hit Ratio",
                "type": "timeseries",
                "promql": 'pg_stat_database_blks_hit / (pg_stat_database_blks_hit + pg_stat_database_blks_read) * 100',
                "current_value": f"{db_mem.get('cache_hit_pct', 99.4)}%",
                "status": "DEGRADED" if is_leak else "NORMAL"
            },
            {
                "id": 3,
                "title": "PostgreSQL Shared Buffers In-Use",
                "type": "stat",
                "promql": 'pg_stat_shared_buffers_allocated_bytes',
                "current_value": f"{db_mem.get('shared_buffers_gb', 4.2)} GB / 8.0 GB",
                "status": "NORMAL"
            },
            {
                "id": 4,
                "title": "Active WorkMem Leased",
                "type": "stat",
                "promql": 'sum(pg_backend_work_mem_bytes)',
                "current_value": "2,450 MB (High Session Retained)" if is_leak else "128 MB (Normal)",
                "status": "WARNING" if is_leak else "NORMAL"
            }
        ]
    else:
        # Default All-in-One Grafana View (Connection Pool, Latency, TPS)
        title = "HikariCP & PostgreSQL Production Database Telemetry"
        uid = "hikari-postgres-pool"
        alert_name = "HikariPoolExhaustion" if is_leak else "PoolWithinSLA"
        panels = [
            {
                "id": 1,
                "title": "HikariCP Connection Pool Saturation",
                "type": "gauge",
                "promql": 'db_connection_pool_active_connections{pool="HikariPool-1"} / db_connection_pool_max_connections{pool="HikariPool-1"} * 100',
                "current_value": f"{metrics['active_connections']} / {metrics['max_connections']} ({metrics['pool_utilization_pct']}%)",
                "status": "CRITICAL" if is_leak else "NORMAL"
            },
            {
                "id": 2,
                "title": "P99 / P90 / P50 Query Latency (ms)",
                "type": "timeseries",
                "promql": 'histogram_quantile(0.99, sum(rate(db_query_duration_bucket[1m])) by (le))',
                "current_value": f"{metrics['latency_p99_ms']} ms",
                "status": "CRITICAL" if is_leak else "NORMAL"
            },
            {
                "id": 3,
                "title": "DB Query Throughput (TPS)",
                "type": "timeseries",
                "promql": 'sum(rate(db_query_total[1m]))',
                "current_value": f"{metrics['throughput_tps']} TPS",
                "status": "DEGRADED" if is_leak else "NORMAL"
            },
            {
                "id": 4,
                "title": "Hikari Waiting Threads & Acquisition Timeouts",
                "type": "stat",
                "promql": 'db_connection_pool_waiting_threads{pool="HikariPool-1"}',
                "current_value": f"{metrics['waiting_threads']} threads waiting | {metrics['timeout_count']} timeouts",
                "status": "CRITICAL" if is_leak else "NORMAL"
            }
        ]

    alert_status = "ALERTING" if is_leak else "OK"
    return JSONResponse(content={
        "status": "CONNECTED",
        "url": url,
        "view": view,
        "dashboard_uid": uid,
        "dashboard_title": title,
        "datasource": "Prometheus (production-cluster-us-east)",
        "refresh_interval": "5s",
        "time_range": "now-15m to now",
        "alert": {
            "status": alert_status,
            "name": alert_name,
            "severity": "CRITICAL" if is_leak else "INFO",
            "message": f"Critical degradation detected in {title}." if is_leak else f"Subsystem {title} operating within normal SLA."
        },
        "panels": panels,
        "metrics_snapshot": metrics
    })


@app.get("/api/report")
async def get_rca_report_json():
    """Returns the RCA report content as JSON."""
    report_md = state_machine.generate_incident_report_markdown()
    report_doc = state_machine.generate_incident_report_doc()
    return JSONResponse(content={
        "ticket_id": "PERF-512",
        "title": "Database Connection Pool Starvation in OrderService",
        "report_markdown": report_md,
        "report_doc": report_doc
    })

