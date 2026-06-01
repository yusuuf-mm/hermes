"""
db_lock.py
----------
Shared threading lock for serializing DuckDB access across modules.
Used by the telemetry daemon to coordinate between:
  - Event simulator thread (writes raw_events)
  - Agent pipeline (reads unprocessed, writes processed_events + agent_logs)
  - Fleet state reader (reads route_solutions + fleet)
"""

import threading

db_lock = threading.Lock()
