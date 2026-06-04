"""
rerouting_agent.py
------------------
Agent 4 of 5 — Rerouting Agent

Responsibility:
  Given the SLA risk report and classified events, make the re-optimisation
  decision:
    - should_resolve:        True / False
    - urgency:              immediate | within_30_min | monitor_only
    - affected_vehicles:    list of vehicle_ids to re-route
    - strategy:             full_replan | partial_replan | vehicle_swap | hold
    - constraints_to_relax: time_windows | capacity | both | none
    - reason:               structured justification

  This agent is the ONLY agent that can recommend triggering the OR solver.
  If should_resolve is True, run_agents.py will invoke run_solver.py.

  This agent does NOT write routes. The OR solver does that.
  It only makes the invoke/strategy decision.

Model: qwen/qwen3-coder-480b-a35b-instruct (via MODEL_REGISTRY["rerouting"])
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from agents.llm_client import MODEL_REGISTRY, complete
from agents.schemas import (
    ConstraintsToRelax,
    ReroutingDecision,
    Strategy,
    Urgency,
)
from agents.state import HermesState

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "rerouting.txt").read_text(encoding="utf-8")


def run(state: HermesState) -> HermesState:
    """
    LangGraph node function.
    Makes the re-optimisation decision based on SLA risk and event data.
    """
    sla_report        = state.get("sla_risk_report",   {})
    classified_events = state.get("classified_events", [])
    fleet             = state.get("fleet",             [])
    monitoring_summary = state.get("monitoring_summary", "")

    # Safe default if upstream agents produced nothing
    if not sla_report:
        state["rerouting_decision"] = ReroutingDecision(
            should_resolve=False,
            urgency=Urgency.MONITOR_ONLY,
            affected_vehicles=[],
            strategy=Strategy.HOLD,
            constraints_to_relax=ConstraintsToRelax.NONE,
            reason="No SLA risk data available. Holding for next cycle.",
            human_approval_required=False,
        ).model_dump()
        return state

    # Only pass high/critical events to keep the prompt focused
    serious_events = [
        e for e in classified_events
        if e.get("severity") in ("high", "critical")
    ]

    user_message = (
        f"Monitoring summary: {monitoring_summary}\n\n"
        f"SLA Risk Report:\n{json.dumps(sla_report, indent=2)}\n\n"
        f"Serious events ({len(serious_events)}):\n"
        f"{json.dumps(serious_events, indent=2)}\n\n"
        f"Fleet ({len(fleet)} vehicles): "
        f"{[v.get('vehicle_id') for v in fleet]}"
    )

    raw_response = complete(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_message,
        model=MODEL_REGISTRY["rerouting"],
        max_tokens=300,
    )

    try:
        parsed = ReroutingDecision.model_validate_json(raw_response)
    except ValidationError:
        parsed = ReroutingDecision(
            should_resolve=False,
            urgency=Urgency.MONITOR_ONLY,
            affected_vehicles=[],
            strategy=Strategy.HOLD,
            constraints_to_relax=ConstraintsToRelax.NONE,
            reason=f"Rerouting agent parse error: {raw_response[:200]}",
            human_approval_required=True,
        )

    state["rerouting_decision"] = parsed.model_dump()

    return state
