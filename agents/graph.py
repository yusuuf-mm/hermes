"""
graph.py
--------
LangGraph orchestration for the HERMES agent system.

Graph topology:
  monitoring → classification → sla_risk → rerouting → dispatch
                                                 ↓
                                    (conditional) → re_invoke_solver

The only conditional edge is after the Rerouting Agent:
  - If should_resolv=True  → dispatch (solver re-invocation is handled
                              in run_agents.py AFTER the graph completes)
  - If should_resolv=False → dispatch directly

This keeps the graph clean: the solver is an external process, not a
LangGraph node. Agents decide; the pipeline executes.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langgraph.graph import END, StateGraph

from agents.state import HermesState
from agents.telemetry import wrap_agent_node
import agents.monitoring_agent    as monitoring
import agents.classification_agent as classification
import agents.sla_risk_agent       as sla_risk
import agents.rerouting_agent      as rerouting
import agents.dispatch_agent       as dispatch


# ---------------------------------------------------------------------------
# Conditional routing logic
# ---------------------------------------------------------------------------

def should_continue_to_dispatch(state: HermesState) -> str:
    """
    After the Monitoring Agent: if no anomalies, skip classification
    and risk assessment — jump straight to a brief dispatch summary.
    Saves LLM calls when operations are nominal.
    """
    if not state.get("anomalies_detected", False):
        return "dispatch_direct"
    return "classify"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(with_telemetry: bool = False) -> StateGraph:
    graph = StateGraph(HermesState)

    # -- Register nodes (one per agent) ------------------------------------
    # When telemetry is enabled, wrap each node with timing + DB logging
    def _node(name, fn):
        return wrap_agent_node(name, fn) if with_telemetry else fn

    graph.add_node("monitoring",     _node("monitoring",     monitoring.run))
    graph.add_node("classification", _node("classification", classification.run))
    graph.add_node("sla_risk",       _node("sla_risk",       sla_risk.run))
    graph.add_node("rerouting",      _node("rerouting",      rerouting.run))
    graph.add_node("dispatch",       _node("dispatch",       dispatch.run))

    # -- Entry point -------------------------------------------------------
    graph.set_entry_point("monitoring")

    # -- Edges -------------------------------------------------------------
    # Monitoring → conditional branch
    graph.add_conditional_edges(
        "monitoring",
        should_continue_to_dispatch,
        {
            "classify":        "classification",   # anomalies present → full pipeline
            "dispatch_direct": "dispatch",         # nominal → skip to brief
        },
    )

    # Full pipeline path
    graph.add_edge("classification", "sla_risk")
    graph.add_edge("sla_risk",       "rerouting")
    graph.add_edge("rerouting",      "dispatch")

    # Dispatch always terminates the graph
    graph.add_edge("dispatch", END)

    return graph


def compile_graph(with_telemetry: bool = False):
    """Return a compiled, runnable LangGraph app."""
    return build_graph(with_telemetry=with_telemetry).compile()
