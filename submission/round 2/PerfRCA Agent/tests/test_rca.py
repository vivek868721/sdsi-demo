"""
Comprehensive Test Suite for PerfRCA Agent.
Verifies Prometheus metrics, log clustering, institutional memory retrieval,
commit inspection, state-machine trace generation, and FastAPI routes.
"""

import pytest
import asyncio
from fastapi.testclient import TestClient

from app.server import app
from app.telemetry import telemetry_engine
from app.agent.state_machine import PerfRCAStateMachine
from app.agent.memory import InstitutionalMemory
from app.agent.code_repo import CodeRepoEngine
from app.agent.log_engine import LogEngine

client = TestClient(app)


def test_dashboard_endpoint():
    """Verify HTML dashboard is served."""
    response = client.get("/")
    assert response.status_code == 200
    assert "PerfRCA Agent" in response.text
    assert "Live Agent State-Machine Trace" in response.text


def test_prometheus_metrics_endpoint():
    """Verify Prometheus text format /metrics export."""
    response = client.get("/metrics")
    assert response.status_code == 200
    text = response.text
    assert "db_connection_pool_active_connections" in text
    assert "db_query_latency_p99_milliseconds" in text
    assert "db_query_throughput_tps" in text


def test_live_metrics_json():
    """Verify real-time JSON metrics endpoint."""
    response = client.get("/api/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "active_connections" in data
    assert "latency_p99_ms" in data
    assert "throughput_tps" in data
    assert "history" in data
    assert len(data["history"]) > 0


def test_normal_load_control():
    """Verify normal load control resets telemetry to healthy baseline."""
    response = client.post("/api/control/normal")
    assert response.status_code == 200
    assert response.json()["mode"] == "normal"
    telemetry_engine.tick()
    metrics = telemetry_engine.get_current_metrics()
    assert metrics["active_connections"] <= 3.5
    assert metrics["latency_p99_ms"] < 50.0
    assert metrics["throughput_tps"] > 35.0


def test_leak_injection_control():
    """Verify connection leak injection surges pool saturation and latency."""
    response = client.post("/api/control/leak")
    assert response.status_code == 200
    assert response.json()["mode"] == "leak"
    
    # Tick several times to simulate leak buildup
    for _ in range(8):
        telemetry_engine.tick()

    metrics = telemetry_engine.get_current_metrics()
    assert metrics["active_connections"] >= 9.0
    assert metrics["latency_p99_ms"] > 2500.0
    assert metrics["throughput_tps"] < 10.0


def test_institutional_memory_matching():
    """Verify institutional memory correctly scores OPP-3716 as top match."""
    memory = InstitutionalMemory()
    match = memory.match_incident(
        symptom_text="HikariCP connection leak unclosed try-with-resources timeout",
        log_templates=["[HikariPool-1] Connection is not available, request timed out after 30000ms"]
    )
    assert match["incident_id"] == "OPP-3716"
    assert match["confidence_score"] >= 90.0
    assert "try-with-resources" in match["resolution_summary"]


def test_log_clustering_45k():
    """Verify 45,000 log clustering produces expected templates."""
    results = LogEngine.get_cluster_analysis()
    assert results["total_logs_analyzed"] == 45000
    assert len(results["clusters"]) == 4
    dominant = results["clusters"][0]
    assert dominant["count"] == 39812
    assert "Connection is not available" in dominant["template"]


def test_commit_b8f3a9e_attribution_and_fix():
    """Verify commit b8f3a9e inspection and try-with-resources patch."""
    commit = CodeRepoEngine.get_commit_b8f3a9e()
    assert commit["short_hash"] == "b8f3a9e"
    assert "OrderService.java" in commit["file_path"]

    diff = CodeRepoEngine.get_unified_diff()
    assert "+        try (Connection conn = dataSource.getConnection();" in diff

    jira = CodeRepoEngine.generate_jira_ticket()
    assert jira["ticket_id"] == "PERF-512"
    assert jira["priority"] == "P0 - Blocker"
    assert jira["matched_historical_incident"] == "OPP-3716"


def test_state_machine_full_execution():
    """Verify both RCA steps (Metrics + Log Clustering) execute successfully."""
    async def run_test():
        sm = PerfRCAStateMachine(telemetry_engine)
        events = []
        async for event in sm.run_investigation(step_duration=0.05):
            events.append(event)
        return events

    events = asyncio.run(run_test())
    steps_completed = [e["step"] for e in events if e.get("type") == "step_complete"]
    assert steps_completed == [1, 2]

    finish_event = next(e for e in events if e.get("type") == "investigation_finished")
    assert finish_event["status"] == "SUCCESS"
    all_steps = finish_event["all_steps"]
    assert "step1" in all_steps
    assert "step2" in all_steps
    assert "step3" in all_steps
    assert "step4" in all_steps
    assert "step5" in all_steps
    assert all_steps["step3"]["matched_incident_id"] == "OPP-3716"
    assert all_steps["step4"]["commit_hash"] == "b8f3a9e"
    assert all_steps["step5"]["jira_ticket"]["ticket_id"] == "PERF-512"


def test_download_report_endpoint():
    """Verify downloading the Word (.doc) RCA Report document."""
    response = client.get("/api/report/download")
    assert response.status_code == 200
    assert "attachment" in response.headers.get("Content-Disposition", "")
    assert "PerfRCA_Incident_Report_PERF-512.doc" in response.headers.get("Content-Disposition", "")
    assert "application/msword" in response.headers.get("Content-Type", "")
    content = response.text
    assert "Incident Root Cause Analysis" in content
    assert "PERF-512" in content
    assert "OPP-3716" in content
    assert "b8f3a9e" in content
    assert "try-with-resources" in content


def test_report_json_endpoint():
    """Verify getting report markdown as JSON."""
    response = client.get("/api/report")
    assert response.status_code == 200
    data = response.json()
    assert data["ticket_id"] == "PERF-512"
    assert "report_markdown" in data
    assert len(data["report_markdown"]) > 100


def test_grafana_inspect_endpoint():
    """Verify inspecting a target Grafana dashboard URL."""
    custom_url = "http://grafana.internal:3000/d/orders-prod/latency-p99-tps"
    response = client.post("/api/grafana/inspect", json={"url": custom_url})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "CONNECTED"
    assert data["url"] == custom_url
    assert "panels" in data
    assert len(data["panels"]) == 4
    assert data["panels"][0]["title"] == "HikariCP Connection Pool Saturation"
    assert "promql" in data["panels"][0]
    assert "alert" in data


def test_subsystem_dropdown_views():
    """Verify all 5 subsystem telemetry views return tailored metrics & panels."""
    views = ["grafana", "app_cpu", "app_memory", "db_cpu", "db_memory"]
    for view in views:
        res = client.post("/api/grafana/inspect", json={"url": "http://localhost:3000/test", "view": view})
        assert res.status_code == 200
        d = res.json()
        assert d["view"] == view
        assert len(d["panels"]) == 4
        assert "metrics_snapshot" in d
        assert "subsystems" in d["metrics_snapshot"]
        assert "app_cpu" in d["metrics_snapshot"]["subsystems"]
        assert "app_memory" in d["metrics_snapshot"]["subsystems"]
        assert "db_cpu" in d["metrics_snapshot"]["subsystems"]
        assert "db_memory" in d["metrics_snapshot"]["subsystems"]



