"""
state.py
--------
The single TypedDict that flows through the LangGraph.
Every agent reads from this state and writes its outputs back into it.
No agent shares mutable data through any other channel.
"""

from __future__ import annotations

from typing import Any, Optional
from typing_extensions import TypedDict


class HermesState(TypedDict):
    """
    Shared state object for the HERMES LangGraph.

    Field ownership:
      monitoring_agent    → raw_events, anomalies_detected, monitoring_summary
      classification_agent→ classified_events
      sla_risk_agent      → sla_risk_report
      rerouting_agent     → rerouting_decision
      dispatch_agent      → dispatch_brief
    """

    # ── Input context (loaded before graph runs) ──────────────────────────
    run_id:            str               # current solver run being monitored
    current_routes:    list[dict]        # route_solutions rows for this run
    solution_metadata: dict              # single solution_metadata row
    fleet:             list[dict]        # fleet table rows

    # ── Monitoring Agent outputs ──────────────────────────────────────────
    raw_events:          list[dict]      # raw_events rows (unprocessed)
    anomalies_detected:  bool            # True if any anomaly found
    monitoring_summary:  str            # plain-text summary of observations

    # ── Classification Agent outputs ─────────────────────────────────────
    classified_events:   list[dict]     # each event enriched with severity + category

    # ── SLA Risk Agent outputs ────────────────────────────────────────────
    sla_risk_report:     dict           # {overall_risk, at_risk_nodes, reasoning}

    # ── Rerouting Agent outputs ───────────────────────────────────────────
    rerouting_decision:  dict           # {should_resolv, reason, affected_vehicles}

    # ── Dispatch Agent outputs ────────────────────────────────────────────
    dispatch_brief:      str            # final plain-language brief for operators
