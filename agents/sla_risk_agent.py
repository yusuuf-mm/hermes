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

Model: SLA_RISK_MODEL — openai/gpt-oss-120b:free
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.llm_client import SLA_RISK_MODEL, complete
from agents.state import HermesState

SYSTEM_PROMPT = """You are the SLA Risk Agent for HERMES, an AI-powered logistics operations platform.

Your sole responsibility is to quantify the risk of Service Level Agreement (SLA) breaches — specifically, the risk that one or more deliveries will miss their committed customer time windows.

You receive:
1. The current optimised route plan (vehicle routes, stop sequences, scheduled arrival times)
2. A list of classified operational events (with severity and category)
3. Fleet information (vehicle capacities and shift limits)

Your output must be a JSON object with exactly these fields:
{
  "overall_risk_level": "low|medium|high|critical",
  "sla_risk_score": 0.0 to 1.0,
  "at_risk_nodes": [list of node_ids where time windows are at risk],
  "at_risk_vehicles": [list of vehicle_ids implicated],
  "risk_factors": ["list of specific factors driving the risk score"],
  "reasoning": "3-5 sentence explanation of your risk assessment"
}

Risk scoring guidance:
- sla_risk_score 0.0–0.2: nominal, no action likely needed
- sla_risk_score 0.2–0.5: elevated, monitor closely
- sla_risk_score 0.5–0.8: high, intervention likely needed
- sla_risk_score 0.8–1.0: critical, immediate action required

Key risk drivers to consider:
- Traffic disruptions on arcs that feed time-sensitive stops (narrow tw_close windows)
- Vehicle breakdowns removing capacity from active routes
- Route deviations causing time loss on vehicles with tight remaining schedules
- Failed deliveries requiring retry stops adding time to routes
- New high-priority orders requiring insertion into already-tight routes

Return ONLY the JSON object. No preamble, no markdown fences."""


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
        model=SLA_RISK_MODEL,
        max_tokens=800,
    )

    try:
        report = json.loads(raw_response)
    except json.JSONDecodeError:
        report = {
            "overall_risk_level": "high",
            "sla_risk_score":     0.7,
            "at_risk_nodes":      [],
            "at_risk_vehicles":   [],
            "risk_factors":       ["parse_error"],
            "reasoning":          f"SLA risk agent parse error. Raw: {raw_response[:200]}",
        }

    state["sla_risk_report"] = report

    print(
        f"  [SLA Risk]       score={report.get('sla_risk_score', '?')} | "
        f"level={report.get('overall_risk_level', '?')} | "
        f"at_risk_nodes={report.get('at_risk_nodes', [])}"
    )
    return state
