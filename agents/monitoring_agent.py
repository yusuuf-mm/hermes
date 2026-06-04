"""
monitoring_agent.py
-------------------
Agent 1 of 5 — Monitoring Agent

Responsibility:
  Observe the raw_events stream from DuckDB.
  Identify whether any anomalies exist that require operational attention.
  Produce a concise monitoring summary for the Classification Agent.

This agent does NOT classify events, does NOT assess SLA risk,
and does NOT make routing decisions. It only observes and flags.

Model: meta/llama-4-maverick-17b-128e-instruct (via MODEL_REGISTRY["monitoring"])
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from agents.llm_client import MODEL_REGISTRY, complete
from agents.schemas import MonitoringOutput
from agents.state import HermesState

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "monitoring.txt").read_text(encoding="utf-8")


def run(state: HermesState) -> HermesState:
    """
    LangGraph node function.
    Reads raw_events from state, calls the LLM, writes results back to state.
    """
    raw_events = state.get("raw_events", [])

    if not raw_events:
        state["anomalies_detected"]  = False
        state["monitoring_summary"]  = "No events in the current window. Operations nominal."
        return state

    # Build a compact, token-efficient event summary for the prompt
    event_lines = []
    for evt in raw_events:
        payload_str = json.dumps(evt.get("payload", {}))[:200]   # truncate large payloads
        event_lines.append(
            f"- [{evt['event_type']}] vehicle={evt.get('vehicle_id', 'N/A')} "
            f"node={evt.get('node_id', 'N/A')} payload={payload_str}"
        )

    user_message = (
        f"Current route run: {state.get('run_id', 'UNKNOWN')}\n"
        f"Events to analyse ({len(raw_events)} total):\n"
        + "\n".join(event_lines)
    )

    raw_response = complete(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_message,
        model=MODEL_REGISTRY["monitoring"],
        max_tokens=200,
    )

    try:
        parsed = MonitoringOutput.model_validate_json(raw_response)
    except ValidationError:
        # Graceful degradation — if LLM returns malformed JSON, flag for review
        parsed = MonitoringOutput(
            anomalies_detected=True,
            anomaly_count=len(raw_events),
            anomaly_types=["parse_error"],
            monitoring_summary=f"Monitoring agent parse error. Raw: {raw_response[:200]}",
        )

    state["anomalies_detected"] = parsed.anomalies_detected
    state["monitoring_summary"] = parsed.monitoring_summary

    return state
