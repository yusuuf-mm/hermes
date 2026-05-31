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

Model: DISPATCH_MODEL — google/gemma-4-31b:free
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import duckdb

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.llm_client import DISPATCH_MODEL, complete
from agents.state import HermesState

DB_PATH = os.environ.get("HERMES_DB_PATH", "hermes.duckdb")

SYSTEM_PROMPT = """You are the Dispatch Recommendation Agent for HERMES, an AI-powered logistics platform.

You are the final voice of the system. Your output is read directly by human dispatchers and operations managers making real-time decisions.

You receive a complete operational picture:
- Monitoring summary (what was observed)
- Classified events (what happened and how serious)
- SLA risk report (what is at risk and why)
- Rerouting decision (what the system recommends)

Write a structured operations brief. It must follow this exact format:

SITUATION
[2-3 sentences: what is happening right now in the field]

SLA RISK
[2-3 sentences: which deliveries are at risk, which vehicles are implicated, and the risk score]

SYSTEM RECOMMENDATION
[1-2 sentences: what the system has decided (re-solve or hold) and why]

IMMEDIATE ACTIONS
[Numbered list of 2-4 specific actions the dispatcher should take right now]

STATUS
[One word or phrase: NOMINAL / ELEVATED / CRITICAL / RE-OPTIMISING]

Rules:
- Be direct. Dispatchers do not have time for hedging language.
- Use vehicle IDs (VH-001) and node IDs where relevant.
- If human approval is required before re-solving, state it explicitly in IMMEDIATE ACTIONS.
- If the system recommends holding, explain what to watch for.
- Do not use bullet points for SITUATION, SLA RISK, or SYSTEM RECOMMENDATION — prose only.
- IMMEDIATE ACTIONS must be numbered and actionable (verb-first sentences).

Return only the brief. No preamble."""


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
        model=DISPATCH_MODEL,
        max_tokens=800,
    )

    state["dispatch_brief"] = brief

    # -- Write processed_events back to DuckDB ----------------------------
    _persist_processed_events(state)

    print(f"  [Dispatch]       Brief generated ({len(brief)} chars)")
    print("\n" + "=" * 60)
    print("HERMES DISPATCH BRIEF")
    print("=" * 60)
    print(brief)
    print("=" * 60 + "\n")

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
        print(f"  [Dispatch]       {len(rows)} events written to processed_events")
    except Exception as e:
        print(f"  [Dispatch]       DB write warning: {e}")
