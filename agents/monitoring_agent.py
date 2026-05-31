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

Model: MONITORING_MODEL — deepseek/deepseek-v4-flash:free
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.llm_client import MONITORING_MODEL, complete
from agents.state import HermesState

SYSTEM_PROMPT = """You are the Monitoring Agent for HERMES, an AI-powered logistics operations platform.

Your sole responsibility is to observe incoming logistics events and determine whether anomalies exist that require operational attention.

You receive a list of raw events from the field. Each event has a type, a vehicle ID, a node ID, and a payload.

Event types you may see:
- vehicle_telemetry: GPS pings, speed, fuel, engine status
- route_deviation: vehicle significantly off planned route
- traffic_disruption: congestion or road incidents affecting arcs
- failed_delivery: delivery could not be completed
- live_order: new order arrived after routes started
- vehicle_breakdown: vehicle is immobilised

Your output must be a JSON object with exactly these fields:
{
  "anomalies_detected": true or false,
  "anomaly_count": integer,
  "anomaly_types": ["list", "of", "event", "types", "that", "are", "anomalous"],
  "monitoring_summary": "2-3 sentence plain English summary of what you observed"
}

Rules:
- vehicle_telemetry alone is NOT an anomaly unless fuel_pct < 15 or engine_status is 'off'
- Any route_deviation, traffic_disruption, failed_delivery, live_order, or vehicle_breakdown IS an anomaly
- Be precise. Do not inflate the severity of what you see.
- Return ONLY the JSON object. No preamble, no markdown fences."""


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
        model=MONITORING_MODEL,
        max_tokens=400,
    )

    try:
        result = json.loads(raw_response)
    except json.JSONDecodeError:
        # Graceful degradation — if LLM returns malformed JSON, flag for review
        result = {
            "anomalies_detected": True,
            "anomaly_count": len(raw_events),
            "anomaly_types": ["parse_error"],
            "monitoring_summary": f"Monitoring agent parse error. Raw: {raw_response[:200]}",
        }

    state["anomalies_detected"] = result.get("anomalies_detected", False)
    state["monitoring_summary"] = result.get("monitoring_summary", "")

    print(
        f"  [Monitoring]    anomalies={state['anomalies_detected']} | "
        f"summary: {state['monitoring_summary'][:80]}..."
    )
    return state
