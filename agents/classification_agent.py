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

Model: google/gemma-3n-e2b-it (via MODEL_REGISTRY["ingestion"])
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from agents.llm_client import MODEL_REGISTRY, complete  # role key: "ingestion"
from agents.schemas import Category, ClassificationOutput, ClassifiedEvent, Severity
from agents.state import HermesState

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "ingestion.txt").read_text(encoding="utf-8")


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
        model=MODEL_REGISTRY["ingestion"],  # graph node is "classification"
        max_tokens=400,
    )

    try:
        parsed = ClassificationOutput.model_validate_json(raw_response)
    except ValidationError:
        # Fallback: mark all events as medium/operational
        parsed = ClassificationOutput([
            ClassifiedEvent(
                event_id=evt["event_id"],
                event_type=evt["event_type"],
                severity=Severity.MEDIUM,
                category=Category.OPERATIONAL,
                operational_impact="Classification failed — manual review required.",
            )
            for evt in events_for_prompt
        ])

    classified = [e.model_dump() for e in parsed.root]
    state["classified_events"] = classified

    severity_counts = {}
    for e in classified:
        s = e.get("severity", "unknown")
        severity_counts[s] = severity_counts.get(s, 0) + 1

    return state
