"""
PerfRCA Agent Application Entry Point
Starts the Uvicorn web server hosting FastAPI, Prometheus /metrics, and the real-time SRE Dashboard.
"""

import sys
import os
import uvicorn
from dotenv import load_dotenv

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("DEBUG", "false").lower() == "true"

    print("=" * 70)
    print(" [*] Starting PerfRCA Agent - Autonomous Performance Root Cause Analysis")
    print(f" [*] Dashboard URL:       http://localhost:{port}")
    print(f" [*] Prometheus Metrics:  http://localhost:{port}/metrics")
    print("=" * 70)

    uvicorn.run(
        "app.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )
