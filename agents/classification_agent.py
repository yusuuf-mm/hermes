"""
classification_agent.py
-----------------------
Agent 2 of 5 — Event Classification Agent

Responsibility:
  Take each raw event and enrich it with:
    - severity:  low | medium | high | critical
    - category:  operational | safety | sla_risk | capacity | new_demand
    - operational_impact: one-line description of what this means for the plan

  This agent does NOT assess SLA risk (that is Agent 3's job).
  It only classifies. Output feeds directly into the SLA Risk Agent.

Model: CLASSIFICATION_MODEL — minimax/minimax-m2.5:free
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.llm_client import CLASSIFICATION_MODEL, complete
from agents.state import HermesState

SYSTEM_PROMPT = """You are the Event Classification Agent for HERMES, an AI-powered logistics platform.

Your sole responsibility is to classify each logistics event by severity and operational category.

Severity levels:
- low:      informational, no immediate action needed
- medium:   may affect operations within the next 2 hours
- high:     actively degrading current route execution
- critical: requires immediate intervention

Categories:
- operational:  affects vehicle movement or route execution
- safety:       risk to driver, vehicle, or public
- sla_risk:     threatens customer time-window delivery commitments
- capacity:     affects vehicle load or fleet availability
- new_demand:   new orders or demand changes arriving post-route-start

You will receive a list of events. For EACH event, return a classification object.

Return a JSON array. Each element must have:
{
  "event_id": "the original event_id",
  "event_type": "the original event_type",
  "severity": "low|medium|high|critical",
  "category": "operational|safety|sla_risk|capacity|new_demand",
  "operational_impact": "one sentence describing what this means for the active routes"
}

Classification rules:
- vehicle_breakdown → critical, safety
- failed_delivery → medium or high (high if 3rd attempt), sla_risk
- route_deviation > 5km → high, operational
- route_deviation <= 5km → medium, operational
- traffic_disruption with congestion_factor > 2.0 → high, sla_risk
- traffic_disruption with congestion_factor <= 2.0 → medium, operational
- live_order with priority=critical → high, new_demand
- live_order with priority=standard → low, new_demand
- vehicle_telemetry with fuel_pct < 15 → high, safety
- vehicle_telemetry (normal) → low, operational

Return ONLY the JSON array. No preamble, no markdown fences."""


def run(state: HermesState) -> HermesState:
    """
    LangGraph node function.
    Classifies all raw events regardless of anomaly flag —
    the SLA Risk Agent needs full event context to score properly.
    """
    raw_events = state.get("raw_events", [])

    if not raw_events:
        state["classified_events"] = []
        return state

    # Build event list for the prompt — include key payload fields
    events_for_prompt = []
    for evt in raw_events:
        payload = evt.get("payload", {})
        # Extract the most classification-relevant fields only
        relevant = {
            k: v for k, v in payload.items()
            if k in (
                "deviation_km", "congestion_factor", "reason",
                "attempt_count", "priority", "fuel_pct",
                "engine_status", "breakdown_type", "demand_units",
            )
        }
        events_for_prompt.append({
            "event_id":   evt["event_id"],
            "event_type": evt["event_type"],
            "vehicle_id": evt.get("vehicle_id"),
            "node_id":    evt.get("node_id"),
            "key_fields": relevant,
        })

    user_message = (
        f"Classify the following {len(events_for_prompt)} events:\n"
        + json.dumps(events_for_prompt, indent=2)
    )

    raw_response = complete(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_message,
        model=CLASSIFICATION_MODEL,
        max_tokens=1000,
    )

    try:
        classified = json.loads(raw_response)
        if not isinstance(classified, list):
            raise ValueError("Expected a JSON array")
    except (json.JSONDecodeError, ValueError):
        # Fallback: mark all events as medium/operational
        classified = [
            {
                "event_id":           evt["event_id"],
                "event_type":         evt["event_type"],
                "severity":           "medium",
                "category":           "operational",
                "operational_impact": "Classification failed — manual review required.",
            }
            for evt in events_for_prompt
        ]

    state["classified_events"] = classified

    severity_counts = {}
    for e in classified:
        s = e.get("severity", "unknown")
        severity_counts[s] = severity_counts.get(s, 0) + 1

    print(
        f"  [Classification] {len(classified)} events classified | "
        + " | ".join(f"{s}={n}" for s, n in sorted(severity_counts.items()))
    )
    return state
