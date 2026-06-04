"""
solver_bridge.py
----------------
Invoke the OR-Tools CVRPTW solver as an external subprocess.

Tool: solver_bridge

This is a SCHEMA-ONLY skeleton. The stub returns a 'NOT_INVOKED' status.
Future work will:
  1. Wire this into agents/llm_client.py::complete() via the OpenAI
     `tools` parameter for function-calling.
  2. Replace the stub body with subprocess.run() to assets/optimization/run_solver.py.
  3. Stream stdout/stderr for live progress display.

Architectural note: the solver is intentionally kept OUT of the LangGraph
graph (see CLAUDE.md "Execution Isolation"). This tool preserves that
boundary by spawning the solver as a subprocess.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SolverBridgeStatus(str, Enum):
    """Status returned by the solver subprocess."""
    OPTIMAL          = "OPTIMAL"
    SUCCESS          = "SUCCESS"
    INFEASIBLE       = "INFEASIBLE"
    NOT_SOLVED       = "NOT_SOLVED"
    FAIL             = "FAIL"
    FAIL_TIMEOUT     = "FAIL_TIMEOUT"
    NOT_INVOKED      = "NOT_INVOKED"   # stub / dry-run
    SUBPROCESS_ERROR = "SUBPROCESS_ERROR"


class SolverBridgeInput(BaseModel):
    """Input for the solver_bridge tool."""
    scenario_tag:  str = Field(
        default="active_disruption",
        description="Scenario tag written to solution_metadata.scenario_tag.",
    )
    time_limit_s:  int = Field(
        default=60, ge=1, le=3600,
        description="Maximum wall-clock seconds the solver may run.",
    )
    dry_run:      bool = Field(
        default=False,
        description="If true, return NOT_INVOKED without spawning subprocess (for testing).",
    )


class SolverBridgeOutput(BaseModel):
    """Output of the solver_bridge tool."""
    status:        SolverBridgeStatus
    returncode:    int   = Field(description="Process return code (0 = success, -1 = dry-run).")
    duration_s:    float = Field(ge=0.0, description="Wall-clock duration of the subprocess.")
    stdout_tail:   str   = Field(default="", description="Last 1KB of stdout for diagnostics.")
    stderr_tail:   str   = Field(default="", description="Last 1KB of stderr for diagnostics.")


# ---------------------------------------------------------------------------
# Stub function — to be implemented in the tool-calling integration phase
# ---------------------------------------------------------------------------

def invoke_solver(input: SolverBridgeInput) -> SolverBridgeOutput:
    """
    Invoke assets/optimization/run_solver.py as a subprocess.

    CURRENTLY A STUB. Returns NOT_INVOKED. The real implementation will:
      - subprocess.run([sys.executable, 'assets/optimization/run_solver.py'],
                       env={..., 'HERMES_SCENARIO_TAG': input.scenario_tag,
                                'SOLVER_TIME_LIMIT_S': str(input.time_limit_s)},
                       capture_output=True, text=True, timeout=input.time_limit_s + 30)
      - Parse returncode → SolverBridgeStatus.
      - Truncate stdout/stderr to last 1KB each.
    """
    return SolverBridgeOutput(
        status=SolverBridgeStatus.NOT_INVOKED,
        returncode=-1,
        duration_s=0.0,
        stdout_tail="",
        stderr_tail="",
    )
