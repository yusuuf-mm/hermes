"""
rerouting_agent.py
------------------
Agent 4 of 5 — Rerouting Agent

Responsibility:
  Given the SLA risk report and classified events, make the re-optimisation
  decision:
    - should_resolv:        True / False
    - urgency:              immediate | within_30_min | monitor_only
    - affected_vehicles:    list of vehicle_ids to re-route
    - strategy:             full_replan | partial_replan | vehicle_swap | hold
    - constraints_to_relax: time_windows | capacity | both | none
    - reason:               structured justification

  This agent is the ONLY agent that can recommend triggering the OR solver.
  If should_resolv is True, run_agents.py will invoke run_solver.py.

  This agent does NOT write routes. The OR solver does that.
  It only makes the invoke/strategy decision.

Model: REROUTING_MODEL — nvidia/nemotron-3-super:free
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.llm_client import REROUTING_MODEL, complete
from agents.state import HermesState

SYSTEM_PROMPT = """You are the Rerouting Agent for HERMES, an AI-powered logistics operations platform.

You are the decision authority for re-optimisation. You receive a full operational picture:
- Current SLA risk assessment (score, at-risk nodes, risk factors)
- Classified operational events (severity, category, impact)
- Fleet status summary

Your sole output is a re-optimisation decision. You must decide:
1. WHETHER to trigger the OR-Tools solver for a new route plan
2. HOW URGENTLY to act
3. WHICH vehicles to include in the re-plan
4. WHAT STRATEGY to apply
5. WHETHER any constraints should be relaxed

Return a JSON object with exactly these fields:
{
  "should_resolv": true or false,
  "urgency": "immediate|within_30_min|monitor_only",
  "affected_vehicles": ["VH-001", "VH-002"],
  "strategy": "full_replan|partial_replan|vehicle_swap|hold",
  "constraints_to_relax": "time_windows|capacity|both|none",
  "reason": "2-3 sentence justification for your decision",
  "human_approval_required": true or false
}

Decision logic:
- sla_risk_score >= 0.8 OR vehicle_breakdown present → should_resolv=true, urgency=immediate
- sla_risk_score 0.5–0.8 AND high-severity events → should_resolv=true, urgency=within_30_min
- sla_risk_score 0.2–0.5 → should_resolv=false, urgency=monitor_only
- sla_risk_score < 0.2 → should_resolv=false, urgency=monitor_only

Strategy guidance:
- full_replan: breakdown or multiple high-severity events across fleet
- partial_replan: 1-2 affected vehicles, rest of fleet nominal
- vehicle_swap: one vehicle down, reassign its stops to others
- hold: risk is elevated but re-solving now would be premature (await more data)

Human approval rules:
- Always require human approval if constraints_to_relax is not 'none'
- Always require human approval for full_replan
- Immediate urgency with full_replan → flag as critical for dispatcher

Return ONLY the JSON object. No preamble, no markdown fences."""


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
        state["rerouting_decision"] = {
            "should_resolv":          False,
            "urgency":                "monitor_only",
            "affected_vehicles":      [],
            "strategy":               "hold",
            "constraints_to_relax":   "none",
            "reason":                 "No SLA risk data available. Holding for next cycle.",
            "human_approval_required": False,
        }
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
        model=REROUTING_MODEL,
        max_tokens=3000,
    )

    try:
        decision = json.loads(raw_response)
    except json.JSONDecodeError:
        decision = {
            "should_resolv":          False,
            "urgency":                "monitor_only",
            "affected_vehicles":      [],
            "strategy":               "hold",
            "constraints_to_relax":   "none",
            "reason":                 f"Rerouting agent parse error: {raw_response[:200]}",
            "human_approval_required": True,
        }

    state["rerouting_decision"] = decision

    flag = "[!] RESOLV TRIGGERED" if decision.get("should_resolv") else "[ok] hold"
    print(
        f"  [Rerouting]      {flag} | "
        f"urgency={decision.get('urgency')} | "
        f"strategy={decision.get('strategy')} | "
        f"human_approval={decision.get('human_approval_required')}"
    )
    return state
