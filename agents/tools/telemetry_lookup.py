"""
telemetry_lookup.py
-------------------
Read historical agent_logs, raw_events, and processed_events from DuckDB.

Tool: telemetry_lookup

This is a SCHEMA-ONLY skeleton. The stub returns an empty result. Future
work will:
  1. Wire this into agents/llm_client.py::complete() via the OpenAI
     `tools` parameter for function-calling.
  2. Replace the stub body with a real DuckDB query.
  3. Add access control (read-only, scoped to recent windows).

Usage (future, post-integration):
    from agents.tools import TOOL_REGISTRY
    fn = TOOL_REGISTRY["telemetry_lookup"]["function"]
    schema = TOOL_REGISTRY["telemetry_lookup"]["input_schema"]
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TelemetryLookupInput(BaseModel):
    """Input for the telemetry_lookup tool."""
    source:     str = Field(
        description="Table to query: 'agent_logs' | 'raw_events' | 'processed_events'",
    )
    run_id:     Optional[str] = Field(
        default=None,
        description="Filter to a specific run_id (omit for latest run).",
    )
    agent_name: Optional[str] = Field(
        default=None,
        description=(
            "Filter agent_logs to a specific agent: 'monitoring' | "
            "'classification' | 'sla_risk' | 'rerouting' | 'dispatch'."
        ),
    )
    since_ts:   Optional[str] = Field(
        default=None,
        description="ISO-8601 lower bound on emitted_at / started_at (inclusive).",
    )
    limit:      int = Field(
        default=100, ge=1, le=1000,
        description="Maximum rows to return (1-1000).",
    )


class TelemetryRow(BaseModel):
    """One row from the queried table (loosely typed)."""
    data: dict


class TelemetryLookupOutput(BaseModel):
    """Output of the telemetry_lookup tool."""
    source:        str   = Field(description="Echoes the source table queried.")
    rows:          list[TelemetryRow]
    total_count:   int   = Field(ge=0, description="Number of rows returned.")
    query_time_ms: float = Field(ge=0.0, description="Wall-clock duration of the query.")


# ---------------------------------------------------------------------------
# Stub function — to be implemented in the tool-calling integration phase
# ---------------------------------------------------------------------------

def lookup_agent_logs(input: TelemetryLookupInput) -> TelemetryLookupOutput:
    """
    Read historical telemetry rows from DuckDB.

    CURRENTLY A STUB. Returns an empty result. The real implementation will:
      - Open a read-only DuckDB connection to HERMES_DB_PATH.
      - Validate `source` against the allowed set.
      - Build a parameterised query with the filters above.
      - Return rows + wall-clock duration.
    """
    return TelemetryLookupOutput(
        source=input.source,
        rows=[],
        total_count=0,
        query_time_ms=0.0,
    )
