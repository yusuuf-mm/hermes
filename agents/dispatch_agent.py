"""
dispatch_agent.py
-----------------
Agent 5 of 5 — Dispatch Recommendation Agent

Responsibility:
  Synthesise the full pipeline output into a single, actionable
  operations brief written for a human dispatcher or operations manager.

  The brief must be:
    - Plain English, no jargon
    - Structured: situation → risk → decision → actions
    - Specific: named vehicles, node IDs, time windows
    - Honest about uncertainty

  This agent also writes the final record to processed_events in DuckDB,
  closing the loop on every event that was observed in this cycle.

Model: google/gemma-3n-e2b-it (via MODEL_REGISTRY["dispatch"])
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import duckdb

from agents.db_lock import db_lock
from agents.llm_client import MODEL_REGISTRY, complete
from agents.state import HermesState

DB_PATH = os.environ.get("HERMES_DB_PATH", "hermes.duckdb")

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "dispatch.txt").read_text(encoding="utf-8")


def run(state: HermesState) -> HermesState:
    """
    LangGraph node function.
    Generates the dispatch brief and writes processed_events to DuckDB.
    """
    monitoring_summary  = state.get("monitoring_summary",  "No monitoring data.")
    classified_events   = state.get("classified_events",   [])
    sla_report          = state.get("sla_risk_report",     {})
    rerouting_decision  = state.get("rerouting_decision",  {})
    run_id              = state.get("run_id", "UNKNOWN")

    user_message = (
        f"Run ID: {run_id}\n\n"
        f"MONITORING SUMMARY:\n{monitoring_summary}\n\n"
        f"CLASSIFIED EVENTS ({len(classified_events)}):\n"
        f"{json.dumps(classified_events[:10], indent=2)}\n\n"   # cap at 10 for prompt budget
        f"SLA RISK REPORT:\n{json.dumps(sla_report, indent=2)}\n\n"
        f"REROUTING DECISION:\n{json.dumps(rerouting_decision, indent=2)}"
    )

    brief = complete(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_message,
        model=MODEL_REGISTRY["dispatch"],
        max_tokens=300,
    )

    # The dispatch brief is free-form text (SITUATION / SLA RISK / ... / STATUS),
    # not a JSON object, so we don't run Pydantic validation here. We do enforce
    # a length envelope and a safe fallback for empty responses. See
    # agents/schemas.py::DispatchOutput for the strict-shape variant.
    brief = (brief or "").strip()
    if not brief:
        brief = "Dispatch brief unavailable — LLM returned empty response."
    elif len(brief) > 4000:
        brief = brief[:4000]

    state["dispatch_brief"] = brief

    # -- Write processed_events back to DuckDB ----------------------------
    _persist_processed_events(state)

    return state


def _persist_processed_events(state: HermesState) -> None:
    """
    Write one processed_events row per classified event, enriched
    with the SLA risk score and the rerouting action taken.
    """
    classified  = state.get("classified_events", [])
    sla_report  = state.get("sla_risk_report",   {})
    decision    = state.get("rerouting_decision", {})

    if not classified:
        return

    sla_score    = sla_report.get("sla_risk_score", 0.0)
    action_taken = decision.get("strategy", "hold")

    rows = [
        (
            evt["event_id"],
            evt.get("severity",           "unknown"),
            evt.get("category",           "operational"),
            sla_score,
            action_taken,
            datetime.utcnow().isoformat(),
        )
        for evt in classified
    ]

    try:
        with db_lock:
            con = duckdb.connect(DB_PATH)
            con.executemany(
                """
                INSERT OR IGNORE INTO processed_events
                    (event_id, severity, category, sla_risk_score,
                     action_taken, processed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            con.close()
    except Exception:
        pass
