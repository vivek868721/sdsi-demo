#!/usr/bin/env python3
"""
Inventory Reservation System — High-Concurrency Benchmark

Launches configurable numbers of concurrent threads against the reservation API,
measuring throughput, correctness (zero oversell), and latency percentiles.

Requirements: pip install httpx
Usage:       python scripts/stress_test.py [--threads 100] [--stock 10] [--sku PS5-CONSOLE]
"""

import argparse
import concurrent.futures
import json
import time
import uuid
import sys
from typing import NamedTuple
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8080"


class InventoryReport(NamedTuple):
    sku: str
    total_stock: int
    available_stock: int
    reserved_stock: int
    sold_stock: int
    invariant_valid: bool


def api_request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """Thin sync HTTP helper using stdlib urllib."""
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Idempotency-Key", str(uuid.uuid4()))
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def get_inventory(sku: str) -> InventoryReport:
    _, data = api_request("GET", f"/api/inventory/{sku}")
    return InventoryReport(
        sku=data["sku"],
        total_stock=data["totalStock"],
        available_stock=data["availableStock"],
        reserved_stock=data["reservedStock"],
        sold_stock=data["soldStock"],
        invariant_valid=data["invariantValid"],
    )


def run_stress_test(sku: str, thread_count: int, stock: int):
    print("=" * 60)
    print(f"  Stress Test: {thread_count} threads racing for {stock} items")
    print("=" * 60)

    # Snapshot before
    before = get_inventory(sku)
    print(f"\n  Before: available={before.available_stock} | reserved={before.reserved_stock} | sold={before.sold_stock}")

    # Launch concurrent reserve requests
    results: list[dict] = []
    successes: list[str] = []
    failures: list[str] = []
    latencies: list[float] = []

    def reserve_worker(idx: int):
        uid = f"stress-user-{idx}"
        t0 = time.monotonic()
        status, data = api_request("POST", "/api/reservations", {
            "sku": sku, "userId": uid, "quantity": 1
        })
        elapsed = time.monotonic() - t0
        if status == 201:
            successes.append(data.get("reservationId", ""))
            return {"success": True, "latency": elapsed, "id": data.get("reservationId")}
        else:
            failures.append(data.get("message", str(status)))
            return {"success": False, "latency": elapsed, "status": status}

    t_start = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as executor:
        futures = [executor.submit(reserve_worker, i) for i in range(thread_count)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
    t_total = time.monotonic() - t_start

    # Collect latencies
    for r in results:
        latencies.append(r["latency"] * 1000)

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]

    # Verify correctness
    after = get_inventory(sku)
    success_count = len(successes)

    print(f"\n  Results:")
    print(f"    Successes:        {success_count}/{thread_count}")
    print(f"    Failures:         {len(failures)}/{thread_count}")
    print(f"    Total time:       {t_total:.3f}s")
    print(f"    Throughput:       {thread_count / t_total:.1f} req/s")
    print(f"    Latency p50:      {p50:.1f} ms")
    print(f"    Latency p95:      {p95:.1f} ms")
    print(f"    Latency p99:      {p99:.1f} ms")

    print(f"\n  Inventory:")
    print(f"    available={after.available_stock} | reserved={after.reserved_stock} | sold={after.sold_stock}")
    print(f"    Invariant valid:  {after.invariant_valid}")

    # Verdict
    if success_count == stock and after.invariant_valid and after.available_stock == before.available_stock - stock:
        print(f"\n  ✅ PASS — No oversell. Exactly {stock} succeeded, invariant holds.")
    else:
        print(f"\n  ❌ FAIL — Expected exactly {stock} successes, got {success_count}.")

    # Confirm all successful reservations
    print(f"\n  Confirming {len(successes)} successful reservations...")
    for rid in successes:
        api_request("POST", f"/api/reservations/{rid}/confirm")

    final = get_inventory(sku)
    print(f"  After confirm: available={final.available_stock} | reserved={final.reserved_stock} | sold={final.sold_stock}")
    if final.sold_stock == stock and final.reserved_stock == 0 and final.invariant_valid:
        print(f"  ✅ Confirm batch OK — all {stock} moved to sold, invariant holds.")

    return {"success_count": success_count, "expected": stock, "invariant_valid": after.invariant_valid}


def run_quota_test(sku: str):
    """10 concurrent requests from the same user when limit=1 → 1 success, 9 fail."""
    print("\n" + "=" * 60)
    print(f"  Quota Test: 10 threads, same user, max_per_user=1")
    print("=" * 60)

    same_user = "quota-test-user"
    successes = []
    failures = []

    def quota_worker(idx: int):
        status, data = api_request("POST", "/api/reservations", {
            "sku": sku, "userId": same_user, "quantity": 1
        })
        if status == 201:
            successes.append(data.get("reservationId", ""))
            return True
        else:
            failures.append(data.get("message", str(status)))
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(quota_worker, i) for i in range(10)]
        concurrent.futures.wait(futures)

    print(f"  Successes: {len(successes)} | Failures: {len(failures)}")
    if len(successes) == 1:
        print(f"  ✅ PASS — Exactly 1 reservation succeeded, per-user quota enforced.")
    else:
        print(f"  ❌ FAIL — Expected 1 success, got {len(successes)}.")

    # Clean up: cancel the successful one
    for rid in successes:
        api_request("POST", f"/api/reservations/{rid}/cancel")


def main():
    parser = argparse.ArgumentParser(description="Inventory Reservation Stress Test")
    parser.add_argument("--threads", type=int, default=100, help="Number of concurrent threads")
    parser.add_argument("--stock", type=int, default=10, help="Available stock for test SKU")
    parser.add_argument("--sku", type=str, default="PS5-CONSOLE", help="Target SKU")
    args = parser.parse_args()

    # Reset: run the stress test SKU separately — we use a dedicated product
    # for quota/stress; for real runs users can point at a freshly seeded DB.
    print("Target:", args.sku, f"| Threads: {args.threads} | Stock: {args.stock}")

    # Run main stress test
    run_stress_test(args.sku, args.threads, args.stock)

    # Run quota test on same SKU (max_per_user may vary; adjust expectations)
    run_quota_test(args.sku)

    print("\n" + "=" * 60)
    print("  Benchmark complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()