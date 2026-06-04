"""
agents/tools/__init__.py
-------------------------
Tool registry for HERMES agents.

Every tool is a (function, input_schema, output_schema, description) tuple
suitable for the OpenAI function-calling `tools` parameter. The registry
is schema-only at this stage — tool-calling integration into
agents/llm_client.py::complete() is a separate phase.

Usage (future, post-integration):
    from agents.tools import TOOL_REGISTRY, to_openai_tools

    # 1) Hand the LLM the tool catalogue.
    response = client.chat.completions.create(
        model=...,
        messages=...,
        tools=to_openai_tools(),   # list of {type:function, function:{...}}
    )

    # 2) If the LLM calls a tool, look it up and execute.
    tool_call = response.choices[0].message.tool_calls[0]
    entry = TOOL_REGISTRY[tool_call.function.name]
    parsed_input = entry["input_schema"].model_validate_json(tool_call.function.arguments)
    result = entry["function"](parsed_input)
"""

from __future__ import annotations

from typing import Any

from agents.tools.notification import (
    NotificationInput,
    NotificationOutput,
    send_notification,
)
from agents.tools.solver_bridge import (
    SolverBridgeInput,
    SolverBridgeOutput,
    invoke_solver,
)
from agents.tools.telemetry_lookup import (
    TelemetryLookupInput,
    TelemetryLookupOutput,
    lookup_agent_logs,
)

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------
# Each entry is keyed by the tool's public name (snake_case). The LLM sees
# this name in the function_call payload.

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "telemetry_lookup": {
        "function":      lookup_agent_logs,
        "input_schema":  TelemetryLookupInput,
        "output_schema": TelemetryLookupOutput,
        "description":   (
            "Read historical agent_logs, raw_events, or processed_events from "
            "DuckDB. Filter by run_id, agent_name, or since_ts. Returns up to "
            "`limit` rows."
        ),
    },
    "solver_bridge": {
        "function":      invoke_solver,
        "input_schema":  SolverBridgeInput,
        "output_schema": SolverBridgeOutput,
        "description":   (
            "Invoke the OR-Tools CVRPTW solver as an external subprocess. "
            "Returns the solver status, duration, and tail of stdout/stderr. "
            "Architecturally, the solver stays outside the LangGraph graph."
        ),
    },
    "notification": {
        "function":      send_notification,
        "input_schema":  NotificationInput,
        "output_schema": NotificationOutput,
        "description":   (
            "Send an operator alert (info / warning / critical) to the "
            "dispatcher. Optionally mark as action_required. Returns the "
            "delivered channels and a notification_id for dedup."
        ),
    },
}


# ---------------------------------------------------------------------------
# OpenAI tool-calling payload helpers
# ---------------------------------------------------------------------------

def to_openai_tools() -> list[dict]:
    """
    Convert TOOL_REGISTRY to the `tools` parameter shape expected by the
    OpenAI chat completions API.

    Each entry is a JSON-schema description of the tool's input. The LLM
    uses this to decide when (and with what arguments) to invoke the tool.
    """
    out: list[dict] = []
    for name, entry in TOOL_REGISTRY.items():
        out.append({
            "type": "function",
            "function": {
                "name":        name,
                "description": entry["description"],
                "parameters":  entry["input_schema"].model_json_schema(),
            },
        })
    return out


def run_tool(name: str, arguments_json: str) -> str:
    """
    Look up a tool by name, validate the JSON arguments, execute the
    function, and serialise the output to JSON. Returns a string suitable
    for feeding back into the LLM as a `tool` role message.

    CURRENTLY UNUSED — kept here for the tool-calling integration phase.
    """
    entry = TOOL_REGISTRY.get(name)
    if entry is None:
        raise ValueError(f"Unknown tool: {name!r}. Available: {list(TOOL_REGISTRY)}")

    parsed_input = entry["input_schema"].model_validate_json(arguments_json)
    output: Any  = entry["function"](parsed_input)
    return entry["output_schema"].model_validate(output).model_dump_json()


__all__ = [
    "TOOL_REGISTRY",
    "to_openai_tools",
    "run_tool",
    # Re-exports for convenience
    "lookup_agent_logs", "TelemetryLookupInput", "TelemetryLookupOutput",
    "invoke_solver",     "SolverBridgeInput",    "SolverBridgeOutput",
    "send_notification", "NotificationInput",    "NotificationOutput",
]
