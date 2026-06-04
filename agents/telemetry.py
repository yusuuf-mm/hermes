"""
telemetry.py
------------
Agent execution logging for the HERMES telemetry feed.

Wraps LangGraph node functions to capture timing, summaries,
and decisions. Writes one row per agent invocation to agent_logs.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Callable

import duckdb

from agents.db_lock import db_lock
from agents.llm_client import MODEL_REGISTRY

DB_PATH = os.environ.get("HERMES_DB_PATH", "hermes.duckdb")


# ---------------------------------------------------------------------------
# Summary extractors — one per agent, pulls the key output from state
# ---------------------------------------------------------------------------

def _extract_monitoring_summary(state: dict) -> tuple[str, str]:
    """Return (output_summary, decision) for the Monitoring Agent."""
    summary = state.get("monitoring_summary", "")
    anomalies = state.get("anomalies_detected", False)
    decision = "anomalies_detected" if anomalies else "nominal"
    return summary[:500], decision


def _extract_classification_summary(state: dict) -> tuple[str, str]:
    """Return (output_summary, decision) for the Classification Agent."""
    events = state.get("classified_events", [])
    if not events:
        return "No events classified", "none"
    counts: dict[str, int] = {}
    for e in events:
        s = e.get("severity", "unknown")
        counts[s] = counts.get(s, 0) + 1
    summary = f"{len(events)} events: " + ", ".join(
        f"{s}={n}" for s, n in sorted(counts.items())
    )
    worst = "critical" if counts.get("critical") else "high" if counts.get("high") else "medium"
    return summary, worst


def _extract_sla_risk_summary(state: dict) -> tuple[str, str]:
    """Return (output_summary, decision) for the SLA Risk Agent."""
    report = state.get("sla_risk_report", {})
    score = report.get("sla_risk_score", 0.0)
    level = report.get("overall_risk_level", "unknown")
    nodes = report.get("at_risk_nodes", [])
    summary = f"Score {score:.2f} ({level}), at-risk nodes: {nodes}"
    return summary[:500], level


def _extract_rerouting_summary(state: dict) -> tuple[str, str]:
    """Return (output_summary, decision) for the Rerouting Agent."""
    d = state.get("rerouting_decision", {})
    should = d.get("should_resolve", False)
    strategy = d.get("strategy", "hold")
    urgency = d.get("urgency", "monitor_only")
    reason = d.get("reason", "")
    summary = f"strategy={strategy}, urgency={urgency}, reason={reason[:200]}"
    decision = f"resolve={should}, {strategy}"
    return summary, decision


def _extract_dispatch_summary(state: dict) -> tuple[str, str]:
    """Return (output_summary, decision) for the Dispatch Agent."""
    brief = state.get("dispatch_brief", "")
    # Extract the STATUS value — format is "STATUS\nVALUE" or "STATUS: VALUE"
    status = "UNKNOWN"
    lines = brief.split("\n")
    for i, line in enumerate(lines):
        if line.strip().upper() == "STATUS":
            # Next non-empty line is the value
            if i + 1 < len(lines):
                status = lines[i + 1].strip()
            break
        elif line.strip().upper().startswith("STATUS:"):
            status = line.split(":", 1)[-1].strip()
            break
    return f"Brief generated ({len(brief)} chars)", status


_SUMMARY_EXTRACTORS: dict[str, Callable[[dict], tuple[str, str]]] = {
    "monitoring":     _extract_monitoring_summary,
    "classification": _extract_classification_summary,
    "sla_risk":       _extract_sla_risk_summary,
    "rerouting":      _extract_rerouting_summary,
    "dispatch":       _extract_dispatch_summary,
}


# ---------------------------------------------------------------------------
# Model name mapping (graph node → MODEL_REGISTRY key)
# ---------------------------------------------------------------------------
#
# Keys are graph node names (DB-continuity). Values are pulled from
# MODEL_REGISTRY in agents.llm_client. The "classification" graph node
# maps to the "ingestion" registry role — same agent, two names.

_AGENT_MODELS: dict[str, str] = {
    "monitoring":     MODEL_REGISTRY["monitoring"],
    "classification": MODEL_REGISTRY["ingestion"],
    "sla_risk":       MODEL_REGISTRY["sla_risk"],
    "rerouting":      MODEL_REGISTRY["rerouting"],
    "dispatch":       MODEL_REGISTRY["dispatch"],
}


# ---------------------------------------------------------------------------
# DB writer
# ---------------------------------------------------------------------------

def write_agent_log(
    tick_id: str,
    run_id: str,
    agent_name: str,
    started_at: str,
    completed_at: str,
    input_summary: str,
    output_summary: str,
    decision: str,
    llm_model: str,
    tokens_used: int = 0,
) -> None:
    """Write a single agent_logs row to DuckDB."""
    try:
        with db_lock:
            con = duckdb.connect(DB_PATH)
            con.execute(
                """
                INSERT INTO agent_logs
                    (tick_id, run_id, agent_name, started_at, completed_at,
                     input_summary, output_summary, decision, llm_model, tokens_used)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tick_id, run_id, agent_name, started_at, completed_at,
                    input_summary, output_summary, decision, llm_model, tokens_used,
                ),
            )
            con.close()
    except Exception as e:
        # Telemetry must never break the pipeline
        print(f"  [Telemetry] DB write warning: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Wrapper factory
# ---------------------------------------------------------------------------

def wrap_agent_node(agent_name: str, node_fn: Callable) -> Callable:
    """
    Wrap a LangGraph node function with telemetry logging.

    The wrapped function:
    1. Records started_at
    2. Calls the original node function
    3. Records completed_at
    4. Extracts output_summary and decision from the resulting state
    5. Writes an agent_logs row

    tick_id and run_id are read from state (set by run_telemetry.py).
    """

    def wrapped(state: dict) -> dict:
        tick_id = state.get("_tick_id", "batch")
        run_id = state.get("run_id", "UNKNOWN")

        # Build input summary from the agent's expected inputs
        input_summary = _build_input_summary(agent_name, state)

        started_at = datetime.now(timezone.utc).isoformat()
        state = node_fn(state)
        completed_at = datetime.now(timezone.utc).isoformat()

        # Extract output summary
        extractor = _SUMMARY_EXTRACTORS.get(agent_name)
        if extractor:
            output_summary, decision = extractor(state)
        else:
            output_summary, decision = "unknown", "unknown"

        llm_model = _AGENT_MODELS.get(agent_name, "unknown")

        write_agent_log(
            tick_id=tick_id,
            run_id=run_id,
            agent_name=agent_name,
            started_at=started_at,
            completed_at=completed_at,
            input_summary=input_summary,
            output_summary=output_summary,
            decision=decision,
            llm_model=llm_model,
        )

        return state

    # Preserve function name for LangGraph
    wrapped.__name__ = node_fn.__name__
    wrapped.__qualname__ = node_fn.__qualname__
    return wrapped


def _build_input_summary(agent_name: str, state: dict) -> str:
    """Build a compact string describing what the agent received as input."""
    if agent_name == "monitoring":
        events = state.get("raw_events", [])
        return f"{len(events)} raw events"
    elif agent_name == "classification":
        events = state.get("raw_events", [])
        return f"{len(events)} events to classify"
    elif agent_name == "sla_risk":
        classified = state.get("classified_events", [])
        routes = state.get("current_routes", [])
        return f"{len(classified)} classified events, {len(routes)} route stops"
    elif agent_name == "rerouting":
        report = state.get("sla_risk_report", {})
        score = report.get("sla_risk_score", 0)
        return f"SLA score {score:.2f}, {len(state.get('classified_events', []))} events"
    elif agent_name == "dispatch":
        decision = state.get("rerouting_decision", {})
        strategy = decision.get("strategy", "none")
        return f"strategy={strategy}, {len(state.get('classified_events', []))} events"
    return ""
