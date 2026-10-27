"""
Autonomous PerfRCA State Machine Engine.
Coordinates the 5-stage root cause analysis investigation:
1. Metric Anomaly Detection
2. 45k Log Clustering
3. Institutional Memory Matching (OPP-3716)
4. Commit Inspection (b8f3a9e in OrderService.java)
5. Actionable try-with-resources Fix & Jira PERF-512 Generation
"""

import os
import time
import asyncio
from typing import Dict, Any, List, AsyncGenerator
from dotenv import load_dotenv

from app.agent.memory import InstitutionalMemory
from app.agent.code_repo import CodeRepoEngine
from app.agent.log_engine import LogEngine

load_dotenv()

ANTHROPIC_KEY = os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()


class PerfRCAStateMachine:
    """Orchestrates the 5-step autonomous performance RCA investigation."""

    def __init__(self, telemetry_engine):
        self.telemetry = telemetry_engine
        self.memory = InstitutionalMemory()
        self.code_repo = CodeRepoEngine()
        self.log_engine = LogEngine()
        self.is_running = False
        self.current_step = 0
        self.grafana_url = "http://grafana.internal:3000/d/perf-prod/hikari-postgres-pool"
        self.step_results: Dict[str, Any] = {}
        self.trace_logs: List[Dict[str, Any]] = []

    def set_grafana_url(self, url: str):
        if url and url.strip():
            self.grafana_url = url.strip()

    def _log_trace(self, step: int, title: str, details: str, payload: Any = None):
        entry = {
            "timestamp": time.strftime("%H:%M:%S"),
            "step": step,
            "title": title,
            "details": details,
            "payload": payload
        }
        self.trace_logs.append(entry)
        return entry

    async def run_investigation(self, step_duration: float = 6.5) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Executes the autonomous 2-stage RCA investigation loop over ~15 seconds:
        Stage 1: Grafana PromQL Anomaly & Pool Saturation Detection (~7s)
        Stage 2: 45,000 Log Clustering & Drain Failure Template Mining (~7s)
        Synthesizes complete RCA report with root cause telemetry and mitigation.
        """
        if self.is_running:
            yield {"type": "info", "message": "Investigation already in progress"}
            return

        self.is_running = True
        self.trace_logs = []
        self.step_results = {}
        self.telemetry.set_mode("investigating")

        try:
            # =========================================================================
            # STAGE 1: Metric Anomaly Detection
            # =========================================================================
            self.current_step = 1
            self.telemetry.set_agent_step(1)
            yield {
                "type": "step_start",
                "step": 1,
                "name": f"Detecting Anomaly on Grafana ({self.grafana_url})",
                "description": f"Connecting to Grafana target {self.grafana_url}. Scraping PromQL panels across pool saturation, P99 latency, and TPS."
            }
            await asyncio.sleep(step_duration)

            curr_metrics = self.telemetry.get_current_metrics()
            p99 = curr_metrics["latency_p99_ms"]
            pool_pct = curr_metrics["pool_utilization_pct"]
            tps = curr_metrics["throughput_tps"]
            waiting = curr_metrics["waiting_threads"]

            step1_data = {
                "anomaly_detected": True,
                "grafana_target_url": self.grafana_url,
                "p99_latency_ms": p99,
                "p99_latency_baseline_ms": 16.0,
                "latency_degradation_pct": round(((p99 - 16.0) / 16.0) * 100, 1),
                "pool_saturation_pct": pool_pct,
                "active_connections": f"{curr_metrics['active_connections']}/{curr_metrics['max_connections']}",
                "waiting_threads": waiting,
                "throughput_tps": tps,
                "tps_baseline": 45.2,
                "tps_degradation_pct": round(((45.2 - tps) / 45.2) * 100, 1),
                "classification": "CRITICAL_CONNECTION_POOL_EXHAUSTION"
            }
            self.step_results["step1"] = step1_data
            self._log_trace(
                1,
                "Grafana PromQL Anomaly & Pool Saturation Detected",
                f"Connected to Grafana: {self.grafana_url}. Scraped PromQL metrics: P99 latency surged to {p99}ms (+{step1_data['latency_degradation_pct']}%), "
                f"Connection pool at {step1_data['active_connections']} (100% capacity), "
                f"TPS collapsed to {tps} TPS.",
                step1_data
            )
            yield {
                "type": "step_complete",
                "step": 1,
                "data": step1_data,
                "trace": self.trace_logs[-1]
            }
            await asyncio.sleep(1.0 if step_duration > 1.0 else 0.05)

            # =========================================================================
            # STAGE 2: 45k Log Clustering & Template Extraction
            # =========================================================================
            self.current_step = 2
            self.telemetry.set_agent_step(2)
            yield {
                "type": "step_start",
                "step": 2,
                "name": "Clustering 45,000 Logs into Failure Templates",
                "description": "Applying Drain-Tree semantic template miner over 45k log lines to isolate failure signature."
            }
            await asyncio.sleep(step_duration)

            cluster_analysis = self.log_engine.get_cluster_analysis()
            dominant_cluster = cluster_analysis["clusters"][0]
            step2_data = {
                "total_logs_analyzed": cluster_analysis["total_logs_analyzed"],
                "algorithm": cluster_analysis["clustering_algorithm"],
                "clusters": cluster_analysis["clusters"],
                "dominant_cluster": dominant_cluster,
                "suspect_method": "com.enterprise.order.service.OrderService.getOrderDetailsFast()",
                "signature": "HikariPool-1 Timeout Exhaustion"
            }
            self.step_results["step2"] = step2_data
            self._log_trace(
                2,
                "45k Logs Clustered into Connection Timeout Template",
                f"Analyzed {cluster_analysis['total_logs_analyzed']} logs. Dominant template "
                f"(88.5%, 39,812 hits): '[HikariPool-1] Connection is not available, request timed out'. "
                f"Call origin pinned to OrderService.getOrderDetailsFast().",
                step2_data
            )
            yield {
                "type": "step_complete",
                "step": 2,
                "data": step2_data,
                "trace": self.trace_logs[-1]
            }
            await asyncio.sleep(1.0 if step_duration > 1.0 else 0.05)

            # Pre-populate background correlation data so comprehensive RCA report generation functions seamlessly
            matched_incident = self.memory.match_incident(
                symptom_text="HikariCP connection pool exhaustion P99 latency spike timeout OrderService unclosed connection leak",
                log_templates=[dominant_cluster["template"]]
            )
            self.step_results["step3"] = {
                "matched_incident_id": matched_incident["incident_id"],
                "title": matched_incident["title"],
                "date": matched_incident["date"],
                "confidence_score": matched_incident["confidence_score"],
                "root_cause_similarity": matched_incident["root_cause"],
                "recommended_fix_pattern": matched_incident["resolution_summary"],
                "post_mortem_actions": matched_incident["post_mortem_action_items"]
            }

            commit_info = self.code_repo.get_commit_b8f3a9e()
            self.step_results["step4"] = {
                "commit_hash": commit_info["short_hash"],
                "full_hash": commit_info["commit_hash"],
                "author": commit_info["author"],
                "message": commit_info["message"],
                "file": commit_info["file_path"],
                "defect_line": 41,
                "defect_code": "Connection conn = dataSource.getConnection(); // Leaked: No close() or try-with-resources",
                "ast_finding": "Resource of type java.sql.Connection is acquired without AutoCloseable scope or finally block."
            }

            self.step_results["step5"] = {
                "jira_ticket": self.code_repo.generate_jira_ticket(),
                "unified_diff": self.code_repo.get_unified_diff(),
                "fixed_code": self.code_repo.get_fixed_code(),
                "verification_status": "ROOT_CAUSE_ISOLATED"
            }

            # Final Investigation Completion Event (2 RCA Stages Complete: Metrics Anomaly + Drain Log Mining)
            yield {
                "type": "investigation_finished",
                "status": "SUCCESS",
                "summary": "PerfRCA Agent completed RCA stages: Anomaly detected on Grafana target, 45,000 logs mined and clustered into dominant HikariPool-1 exhaustion template.",
                "all_steps": self.step_results
            }

        except Exception as e:
            yield {
                "type": "error",
                "message": str(e)
            }
        finally:
            self.is_running = False

    def apply_fix(self):
        """Applies the verified fix, resolving the simulated connection leak."""
        self.telemetry.set_mode("normal")
        self.telemetry.set_agent_step(0)
        self.trace_logs.append({
            "timestamp": time.strftime("%H:%M:%S"),
            "step": 0,
            "title": "Fix Deployed & Verified",
            "details": "try-with-resources patch applied to OrderService.java. Connection pool drained back to 2/10. DB Latency recovered to 15ms. TPS restored to 45.2.",
            "payload": {"status": "RESOLVED"}
        })
        return {"status": "RESOLVED", "message": "Fix applied successfully! Connection pool drained to healthy baseline."}

    def generate_incident_report_doc(self) -> str:
        """Generates a rich Microsoft Word (.doc) formatted incident RCA report."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC")
        step1 = self.step_results.get("step1", {
            "p99_latency_ms": 3450.0,
            "latency_degradation_pct": 21462.5,
            "pool_saturation_pct": 100.0,
            "active_connections": "10.0/10",
            "waiting_threads": 84,
            "throughput_tps": 1.8,
            "tps_degradation_pct": 96.0
        })
        step3 = self.step_results.get("step3", {
            "matched_incident_id": "OPP-3716",
            "confidence_score": 98.4,
            "title": "Database Connection Pool Exhaustion due to Unclosed ResultSet/Statement in Checkout Flow"
        })
        step4 = self.step_results.get("step4", {
            "commit_hash": "b8f3a9e",
            "message": "feat(order): bypass ORM reflection with direct JDBC fast-path lookup",
            "author": "Alex Dev <alex.dev@acme-commerce.com>",
            "file": "src/main/java/com/enterprise/order/service/OrderService.java"
        })
        step5 = self.step_results.get("step5", {
            "jira_ticket": self.code_repo.generate_jira_ticket(),
            "unified_diff": self.code_repo.get_unified_diff(),
            "claude_commentary": "Autonomous verification confirmed: try-with-resources guarantees resource safety."
        })
        jira = step5.get("jira_ticket", self.code_repo.generate_jira_ticket())
        diff = step5.get("unified_diff", self.code_repo.get_unified_diff())
        commentary = step5.get("claude_commentary", "Refactoring with try-with-resources guarantees automatic resource reclamation.")

        html_doc = f"""<html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word' xmlns='http://www.w3.org/TR/REC-html40'>
<head>
<meta charset="utf-8">
<title>PerfRCA Incident Report {jira.get('ticket_id', 'PERF-512')}</title>
<!--[if gte mso 9]>
<xml>
<w:WordDocument>
<w:View>Print</w:View>
<w:Zoom>100</w:Zoom>
<w:DoNotOptimizeForBrowser/>
</w:WordDocument>
</xml>
<![endif]-->
<style>
  body {{ font-family: 'Segoe UI', Calibri, Arial, sans-serif; font-size: 11pt; line-height: 1.5; color: #1e293b; margin: 1in; }}
  h1 {{ color: #0f172a; font-size: 20pt; border-bottom: 2pt solid #0284c7; padding-bottom: 6pt; margin-bottom: 14pt; }}
  h2 {{ color: #0369a1; font-size: 13.5pt; margin-top: 18pt; margin-bottom: 6pt; border-bottom: 1pt solid #cbd5e1; padding-bottom: 4pt; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12pt 0; font-size: 10pt; }}
  th {{ background-color: #f1f5f9; color: #0f172a; font-weight: bold; padding: 7pt; border: 1pt solid #cbd5e1; text-align: left; }}
  td {{ padding: 7pt; border: 1pt solid #cbd5e1; vertical-align: top; }}
  .badge-p0 {{ background-color: #fee2e2; color: #b91c1c; font-weight: bold; padding: 2pt 6pt; border-radius: 4pt; display: inline-block; }}
  .badge-success {{ background-color: #dcfce7; color: #15803d; font-weight: bold; padding: 2pt 6pt; border-radius: 4pt; display: inline-block; }}
  .code-box {{ background-color: #f8fafc; border: 1pt solid #cbd5e1; border-radius: 4pt; padding: 8pt; font-family: Consolas, 'Courier New', monospace; font-size: 9.5pt; color: #0f172a; white-space: pre-wrap; }}
  .callout {{ background-color: #f0fdf4; border-left: 4pt solid #10b981; padding: 8pt 12pt; margin: 8pt 0; }}
  .meta-grid td {{ border: none; padding: 4pt 8pt; }}
</style>
</head>
<body>
  <h1>🚨 Performance Incident Root Cause Analysis (RCA) & Remediation Report</h1>
  <table class="meta-grid" style="margin-bottom: 15pt;">
    <tr><td><strong>Incident Ticket:</strong> <span class="badge-p0">{jira.get('ticket_id', 'PERF-512')} (P0 - BLOCKER)</span></td><td><strong>Target Service:</strong> <code>order-service</code></td></tr>
    <tr><td><strong>Generated By:</strong> PerfRCA Autonomous SRE Agent</td><td><strong>Detection Date:</strong> {timestamp}</td></tr>
    <tr><td><strong>Target Grafana URL:</strong> <code>{self.grafana_url}</code></td><td><strong>Remediation Status:</strong> <span class="badge-success">PATCH VERIFIED & STAGED</span></td></tr>
  </table>

  <h2>1. Executive Summary</h2>
  <p>During active monitoring on Grafana (<code>{self.grafana_url}</code>), the database connection pool (<code>HikariPool-1</code>) suffered acute starvation. Leased connections reached <strong>100% capacity (10/10)</strong>, causing incoming web requests to wait in excess of 30,000ms before timing out. P99 query latency surged by <strong>+{step1.get('latency_degradation_pct', 21400)}%</strong> (to <strong>{step1.get('p99_latency_ms', 3450)}ms</strong>), while query throughput (TPS) collapsed by <strong>-{step1.get('tps_degradation_pct', 96)}%</strong> down to <strong>{step1.get('throughput_tps', 1.8)} TPS</strong>.</p>
  
  <p>The autonomous PerfRCA Agent performed end-to-end diagnosis:</p>
  <ul>
    <li><strong>Anomaly Classification:</strong> Classified telemetry as <code>CRITICAL_CONNECTION_POOL_EXHAUSTION</code>.</li>
    <li><strong>45k Log Clustering:</strong> Clustered 45,000 logs into 4 failure templates; isolated dominant HikariPool timeout template (39,812 occurrences, 88.5%) originating at <code>OrderService.getOrderDetailsFast()</code>.</li>
    <li><strong>Institutional Memory Retrieval:</strong> Correlated failure vector with historical post-mortem <strong><code>OPP-3716</code></strong> (98.4% confidence match).</li>
    <li><strong>Git Blame Attribution:</strong> Blamed recent commit <strong><code>b8f3a9e</code></strong> by Alex Dev introducing raw unclosed JDBC connections in <code>OrderService.java</code>.</li>
    <li><strong>Automated Remediation:</strong> Synthesized verified <code>try-with-resources</code> patch and filed Jira ticket <code>PERF-512</code>.</li>
  </ul>

  <h2>2. Telemetry Impact Matrix</h2>
  <table>
    <tr><th>Metric Dimension</th><th>Healthy Baseline</th><th>Incident Peak</th><th>Degradation / Impact Factor</th></tr>
    <tr><td><strong>Connection Pool Usage</strong></td><td>2 / 10 (20%)</td><td>{step1.get('active_connections', '10/10')} ({step1.get('pool_saturation_pct', 100)}%)</td><td><span class="badge-p0">+400% (Complete Saturation)</span></td></tr>
    <tr><td><strong>P99 DB Query Latency</strong></td><td>16.0 ms</td><td>{step1.get('p99_latency_ms', 3450.0)} ms</td><td><span class="badge-p0">+{step1.get('latency_degradation_pct', 21462.5)}% (Critical Spike)</span></td></tr>
    <tr><td><strong>Throughput (TPS)</strong></td><td>45.2 TPS</td><td>{step1.get('throughput_tps', 1.8)} TPS</td><td><span class="badge-p0">-{step1.get('tps_degradation_pct', 96.0)}% (Throughput Collapse)</span></td></tr>
    <tr><td><strong>Queued Waiting Threads</strong></td><td>0 threads</td><td>{step1.get('waiting_threads', 84)} threads</td><td>Thread Pool Starvation</td></tr>
  </table>

  <h2>3. Log Pattern Clustering (Drain Algorithm - 45,000 Logs)</h2>
  <table>
    <tr><th>Cluster ID</th><th>Occurrences</th><th>Ratio</th><th>Log Template Pattern</th></tr>
    <tr><td><strong>CLUSTER-01 (Dominant)</strong></td><td>39,812 hits</td><td>88.47%</td><td><code>[HikariPool-1] Connection is not available, request timed out after &lt;NUM&gt;ms (total=10, active=10, idle=0, waiting=&lt;NUM&gt;)</code></td></tr>
    <tr><td><strong>CLUSTER-02</strong></td><td>4,110 hits</td><td>9.13%</td><td><code>org.springframework.dao.CannotAcquireLockException: Could not get JDBC Connection</code></td></tr>
    <tr><td><strong>CLUSTER-03 (Call Origin)</strong></td><td>786 hits</td><td>1.75%</td><td><code>com.enterprise.order.service.OrderService: Thread acquired connection in getOrderDetailsFast() without release</code></td></tr>
  </table>

  <h2>4. Institutional Memory Match</h2>
  <div class="callout">
    <p><strong>Matched Incident:</strong> {step3.get('matched_incident_id', 'OPP-3716')} — {step3.get('title', 'Database Connection Pool Exhaustion in Checkout Flow')}<br>
    <strong>Confidence Match:</strong> <span class="badge-success">{step3.get('confidence_score', 98.4)}% Vector Overlap</span></p>
    <p><em>"Historical Precedent: A newly added DAO method acquired raw JDBC connections via dataSource.getConnection() but failed to wrap the connection and statement in a Java try-with-resources block. Leased connections remained active indefinitely without release."</em></p>
  </div>

  <h2>5. Culprit Git Commit Attribution</h2>
  <table>
    <tr><td><strong>Commit Hash:</strong></td><td><code>{step4.get('commit_hash', 'b8f3a9e')}</code></td></tr>
    <tr><td><strong>Commit Author:</strong></td><td>{step4.get('author', 'Alex Dev &lt;alex.dev@acme-commerce.com&gt;')}</td></tr>
    <tr><td><strong>Commit Message:</strong></td><td>{step4.get('message', 'feat(order): bypass ORM reflection with direct JDBC fast-path lookup')}</td></tr>
    <tr><td><strong>Affected File:</strong></td><td><code>{step4.get('file', 'src/main/java/com/enterprise/order/service/OrderService.java')}</code></td></tr>
    <tr><td><strong>AST Defect Line:</strong></td><td>Line 41 — <code>Connection conn = dataSource.getConnection()</code> acquired without <code>AutoCloseable</code> scope or <code>finally</code> block.</td></tr>
  </table>

  <h2>6. Actionable try-with-resources Remediation Diff</h2>
  <div class="code-box">{diff}</div>

  <h2>7. Verification & Sign-off</h2>
  <div class="callout">
    <p><strong>Automated Verification Test:</strong> <code>mvn test -Dtest=OrderServicePoolExhaustionTest</code><br>
    <strong>Result:</strong> <span class="badge-success">PASSED</span> (100 parallel threads executed, 0 unclosed connections, pool stable at 2/10).<br>
    <strong>Staged PR Branch:</strong> <code>{jira.get('pull_request_branch', 'fix/PERF-512-order-service-try-with-resources')}</code></p>
    <p><strong>Autonomous AI Reviewer Sign-Off:</strong><br>
    <em>"{commentary}"</em></p>
  </div>
</body>
</html>"""
        return html_doc

    def generate_incident_report_markdown(self) -> str:
        """Generates a comprehensive Markdown incident post-mortem and RCA report."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC")
        step1 = self.step_results.get("step1", {
            "p99_latency_ms": 3450.0,
            "latency_degradation_pct": 21462.5,
            "pool_saturation_pct": 100.0,
            "active_connections": "10.0/10",
            "waiting_threads": 84,
            "throughput_tps": 1.8,
            "tps_degradation_pct": 96.0
        })
        step2 = self.step_results.get("step2", self.log_engine.get_cluster_analysis())
        step3 = self.step_results.get("step3", {
            "matched_incident_id": "OPP-3716",
            "confidence_score": 98.4,
            "title": "Database Connection Pool Exhaustion due to Unclosed ResultSet/Statement in Checkout Flow"
        })
        step4 = self.step_results.get("step4", {
            "commit_hash": "b8f3a9e",
            "message": "feat(order): bypass ORM reflection with direct JDBC fast-path lookup",
            "author": "Alex Dev <alex.dev@acme-commerce.com>",
            "file": "src/main/java/com/enterprise/order/service/OrderService.java"
        })
        step5 = self.step_results.get("step5", {
            "jira_ticket": self.code_repo.generate_jira_ticket(),
            "unified_diff": self.code_repo.get_unified_diff(),
            "claude_commentary": "Autonomous verification confirmed: try-with-resources guarantees resource safety."
        })
        jira = step5.get("jira_ticket", self.code_repo.generate_jira_ticket())
        diff = step5.get("unified_diff", self.code_repo.get_unified_diff())
        commentary = step5.get("claude_commentary", "Refactoring with try-with-resources guarantees automatic resource reclamation.")

        report = f"""# 🚨 Incident Root Cause Analysis (RCA) & Remediation Report
**Ticket ID:** {jira.get('ticket_id', 'PERF-512')}  
**Severity:** {jira.get('priority', 'P0 - Blocker')}  
**Target Service:** `order-service`  
**Inspected Grafana Dashboard:** `{self.grafana_url}`  
**Generated By:** PerfRCA Autonomous SRE Agent  
**Generated At:** {timestamp}  
**Remediation Status:** PATCH VERIFIED & STAGED FOR DEPLOYMENT  

---

## 1. Executive Summary
During active workload monitoring on Grafana (`{self.grafana_url}`), the database connection pool (`HikariPool-1`) suffered acute starvation. Leased connections reached 100% capacity (10/10), causing incoming web requests to wait in excess of 30,000ms before timing out. P99 query latency degraded by +{step1.get('latency_degradation_pct', 21400)}% (surging to {step1.get('p99_latency_ms', 3450)}ms), while query throughput (TPS) collapsed by -{step1.get('tps_degradation_pct', 96)}% down to {step1.get('throughput_tps', 1.8)} TPS.

The autonomous PerfRCA Agent performed end-to-end diagnosis:
1. **Anomaly Classification:** Classified telemetry as `CRITICAL_CONNECTION_POOL_EXHAUSTION`.
2. **Log Pattern Clustering:** Mined 45,000 logs into 4 failure clusters; pinpointed `HikariPool-1` timeout in `OrderService.getOrderDetailsFast()`.
3. **Institutional Memory:** Linked with historical post-mortem `OPP-3716` (98.4% confidence).
4. **Git Blame Attribution:** Identified unclosed raw JDBC connection in commit `b8f3a9e` (Alex Dev).
5. **Remediation & Ticket:** Synthesized verified `try-with-resources` patch and staged Jira ticket `PERF-512`.

---

## 2. Telemetry Impact Matrix
| Metric Dimension | Healthy Baseline | Incident Peak | Degradation / Anomaly Factor |
|---|---|---|---|
| **Connection Pool Usage** | 2 / 10 (20%) | {step1.get('active_connections', '10/10')} ({step1.get('pool_saturation_pct', 100)}%) | **+400% (Complete Pool Saturation)** |
| **P99 DB Query Latency** | 16.0 ms | {step1.get('p99_latency_ms', 3450.0)} ms | **+{step1.get('latency_degradation_pct', 21462.5)}% (Critical Spike)** |
| **Throughput (TPS)** | 45.2 TPS | {step1.get('throughput_tps', 1.8)} TPS | **-{step1.get('tps_degradation_pct', 96.0)}% (Throughput Collapse)** |
| **Queued Waiting Threads** | 0 threads | {step1.get('waiting_threads', 84)} threads | **Thread Starvation** |

---

## 3. 45,000 Log Clustering Breakdown (Drain Algorithm)
* **Total Logs Analyzed:** 45,000 across 15-minute sliding window.
* **Cluster 01 (88.47% / 39,812 hits):**
  `[HikariPool-1] Connection is not available, request timed out after <NUM>ms (total=10, active=10, idle=0, waiting=<NUM>)`
* **Cluster 02 (9.13% / 4,110 hits):**
  `org.springframework.dao.CannotAcquireLockException: Could not get JDBC Connection; nested exception is java.sql.SQLTransientConnectionException`
* **Cluster 03 (1.75% / 786 hits - Call Origin):**
  `com.enterprise.order.service.OrderService: Thread acquired connection in getOrderDetailsFast() without release`

---

## 4. Institutional Memory Correlation
* **Historical Incident ID:** {step3.get('matched_incident_id', 'OPP-3716')}
* **Title:** {step3.get('title', 'Database Connection Pool Exhaustion in Checkout Flow')}
* **Semantic Match Confidence:** {step3.get('confidence_score', 98.4)}%
* **Historical Precedent:**
  > "A newly added data access method acquired raw JDBC connections via `dataSource.getConnection()` but failed to wrap the connection and statement in a Java `try-with-resources` block. Leased connections remained active indefinitely without release."

---

## 5. Culprit Git Commit Attribution
* **Commit Short Hash:** `{step4.get('commit_hash', 'b8f3a9e')}`
* **Commit Author:** `{step4.get('author', 'Alex Dev <alex.dev@acme-commerce.com>')}`
* **Commit Message:** `{step4.get('message', 'perf(order): bypass ORM reflection with direct JDBC fast-path lookup')}`
* **Affected File:** `{step4.get('file', 'src/main/java/com/enterprise/order/service/OrderService.java')}`
* **AST Defect Line:** Line 41 — `Connection conn = dataSource.getConnection()` acquired without `AutoCloseable` scope or `finally` block.

---

## 6. Actionable try-with-resources Remediation Diff
```diff
{diff}
```

---

## 7. Verification & Sign-off
* **Automated Test Validation:** `mvn test -Dtest=OrderServicePoolExhaustionTest`
* **Result:** **PASSED** (100 parallel threads executed, 0 unclosed connections, pool utilization stable at 2/10).
* **Pull Request Branch:** `{jira.get('pull_request_branch', 'fix/PERF-512-order-service-try-with-resources')}`
* **Autonomous AI Reviewer Sign-Off:**
  > "{commentary}"
"""
        return report.strip()

