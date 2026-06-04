"""
sla_risk_agent.py
-----------------
Agent 3 of 5 — SLA Risk Agent

Responsibility:
  Given classified events and the current route solution, estimate:
    - overall_risk_level: low | medium | high | critical
    - sla_risk_score: 0.0 – 1.0 (probability of at least one SLA breach)
    - at_risk_nodes: list of node_ids where time windows are threatened
    - at_risk_vehicles: vehicles implicated
    - reasoning: structured explanation of the risk assessment

  This agent does NOT decide whether to re-route.
  That is exclusively the Rerouting Agent's responsibility.
  This agent only quantifies and explains the risk.

Model: meta/llama-4-maverick-17b-128e-instruct (via MODEL_REGISTRY["sla_risk"])
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from agents.llm_client import MODEL_REGISTRY, complete
from agents.schemas import RiskLevel, SLARiskReport
from agents.state import HermesState

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "sla_risk.txt").read_text(encoding="utf-8")


def run(state: HermesState) -> HermesState:
    """
    LangGraph node function.
    Combines route data + classified events to produce a risk score.
    """
    classified_events = state.get("classified_events", [])
    current_routes    = state.get("current_routes",    [])
    solution_meta     = state.get("solution_metadata", {})
    fleet             = state.get("fleet",             [])

    if not classified_events:
        state["sla_risk_report"] = {
            "overall_risk_level": "low",
            "sla_risk_score":     0.0,
            "at_risk_nodes":      [],
            "at_risk_vehicles":   [],
            "risk_factors":       [],
            "reasoning":          "No events to assess. Current plan is executing nominally.",
        }
        return state

    # Filter to only actionable events (ignore low-severity telemetry noise)
    actionable = [
        e for e in classified_events
        if e.get("severity") in ("medium", "high", "critical")
    ]

    # Build a compact route summary (avoid sending 100s of stop rows)
    # Group by vehicle, show stop count + earliest/latest arrival
    vehicle_summaries = {}
    for stop in current_routes:
        vid = stop.get("vehicle_id")
        if vid not in vehicle_summaries:
            vehicle_summaries[vid] = {
                "vehicle_id":   vid,
                "stop_count":   0,
                "min_arrival":  float("inf"),
                "max_arrival":  float("-inf"),
                "node_ids":     [],
            }
        vehicle_summaries[vid]["stop_count"]  += 1
        vehicle_summaries[vid]["min_arrival"]  = min(
            vehicle_summaries[vid]["min_arrival"], stop.get("arrival_time", 0)
        )
        vehicle_summaries[vid]["max_arrival"]  = max(
            vehicle_summaries[vid]["max_arrival"], stop.get("arrival_time", 0)
        )
        if stop.get("node_id") != 0:
            vehicle_summaries[vid]["node_ids"].append(stop["node_id"])

    user_message = (
        f"Run ID: {state.get('run_id', 'UNKNOWN')}\n"
        f"Total route cost: {solution_meta.get('total_cost_km', 'N/A')} km\n"
        f"Vehicles in use: {solution_meta.get('vehicles_used', 'N/A')}\n\n"
        f"Vehicle route summaries:\n"
        + json.dumps(list(vehicle_summaries.values()), indent=2)
        + f"\n\nActionable events ({len(actionable)} of {len(classified_events)} total):\n"
        + json.dumps(actionable, indent=2)
    )

    raw_response = complete(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_message,
        model=MODEL_REGISTRY["sla_risk"],
        max_tokens=300,
    )

    try:
        parsed = SLARiskReport.model_validate_json(raw_response)
    except ValidationError:
        parsed = SLARiskReport(
            overall_risk_level=RiskLevel.HIGH,
            sla_risk_score=0.7,
            at_risk_nodes=[],
            at_risk_vehicles=[],
            risk_factors=["parse_error"],
            reasoning=f"SLA risk agent parse error. Raw: {raw_response[:200]}",
        )

    state["sla_risk_report"] = parsed.model_dump()

    return state
