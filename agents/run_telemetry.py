"""
run_telemetry.py
----------------
Continuous telemetry daemon for HERMES agent system.

Polls for unprocessed events on a configurable interval.
Runs the 5-agent LangGraph pipeline with telemetry logging.
Each tick writes agent_logs rows grouped by tick_id.
Displays a Rich three-panel control room UI.
Includes an integrated event simulator thread.

Usage:
    python agents/run_telemetry.py
    make telemetry
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
import uuid
from datetime import datetime, timezone

# Force UTF-8 stdout/stderr on Windows so Rich's Unicode box-drawing
# and emoji don't hit cp1252 encode errors.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import duckdb
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from agents.db_lock import db_lock as _db_lock
load_dotenv("config/.env" if os.path.exists("config/.env") else ".env",
            override=False)

DB_PATH = os.environ.get("HERMES_DB_PATH", "hermes.duckdb")
TICK_INTERVAL_S = int(os.environ.get("HERMES_TICK_INTERVAL_S", "130"))

# Suggested tick intervals per model profile.  The daemon tick should be
# longer than the slowest expected pipeline run, otherwise ticks queue
# and the agent log floods.  Override per-deployment via
# HERMES_TICK_INTERVAL_S in the environment.
_PROFILE_TICK_HINTS_S: dict[str, int] = {
    "demo":     130,    # all-gemma,  ~100-120s pipeline
    "balanced": 90,     # all-qwen,   ~70s pipeline
    "prod":     280,    # maverick+   ~240s pipeline
}
_profile = os.environ.get("HERMES_MODEL_PROFILE", "demo").lower()
TICK_HINT_S = _PROFILE_TICK_HINTS_S.get(_profile, 130)
if TICK_INTERVAL_S < TICK_HINT_S:
    # Soft warning, not a hard override — explicit env var wins.
    # Goes to stderr so it doesn't corrupt the Rich UI redraw.
    print(
        f"[telemetry] HERMES_TICK_INTERVAL_S={TICK_INTERVAL_S} is shorter "
        f"than the recommended {TICK_HINT_S}s for profile '{_profile}'. "
        f"Pipeline runs will overlap.",
        file=sys.stderr,
    )
SIM_INTERVAL_S = float(os.environ.get("HERMES_SIM_INTERVAL_S", "3"))

# Graceful shutdown
_running = True

def _handle_signal(sig, frame):
    global _running
    _running = False

signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

# DB access lock — serializes all DuckDB access from both threads
from agents.db_lock import db_lock as _db_lock


# ---------------------------------------------------------------------------
# Event generator (integrated into tick cycle — no concurrent access)
# ---------------------------------------------------------------------------

def _generate_events(con, count: int = 3) -> int:
    """Generate events as part of the tick. Returns number written."""
    from events.simulator.disruption_generator import pick_event, write_event
    written = 0
    for _ in range(count):
        evt = pick_event()
        write_event(con, evt)
        written += 1
    return written


# ---------------------------------------------------------------------------
# State loader (reuses logic from run_agents.py)
# ---------------------------------------------------------------------------

def load_state(con: duckdb.DuckDBPyConnection) -> dict | None:
    """Build the initial HermesState dict from DuckDB.
    Returns None if there are no unprocessed events."""
    meta_row = con.execute("""
        SELECT run_id, total_cost_km, vehicles_used, orders_served,
               constraint_violations, solve_time_s, solver_status
        FROM solution_metadata
        ORDER BY created_at DESC
        LIMIT 1
    """).fetchone()

    if not meta_row:
        return None

    run_id = meta_row[0]
    solution_metadata = {
        "run_id":                meta_row[0],
        "total_cost_km":         meta_row[1],
        "vehicles_used":         meta_row[2],
        "orders_served":         meta_row[3],
        "constraint_violations": meta_row[4],
        "solve_time_s":          meta_row[5],
        "solver_status":         meta_row[6],
    }

    route_rows = con.execute("""
        SELECT vehicle_id, stop_seq, node_id, arrival_time, departure_time
        FROM route_solutions WHERE run_id = ?
        ORDER BY vehicle_id, stop_seq
    """, [run_id]).fetchall()

    current_routes = [
        {"vehicle_id": r[0], "stop_seq": r[1], "node_id": r[2],
         "arrival_time": r[3], "departure_time": r[4]}
        for r in route_rows
    ]

    fleet_rows = con.execute(
        "SELECT vehicle_id, capacity_units, max_shift_min, depot_id FROM fleet"
    ).fetchall()
    fleet = [
        {"vehicle_id": r[0], "capacity_units": r[1],
         "max_shift_min": r[2], "depot_id": r[3]}
        for r in fleet_rows
    ]

    event_rows = con.execute("""
        SELECT r.event_id, r.event_type, r.vehicle_id, r.node_id,
               r.payload, r.emitted_at
        FROM raw_events r
        LEFT JOIN processed_events p ON r.event_id = p.event_id
        WHERE p.event_id IS NULL
        ORDER BY r.emitted_at ASC LIMIT 50
    """).fetchall()

    if not event_rows:
        return None

    raw_events = []
    for row in event_rows:
        payload = row[4]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        raw_events.append({
            "event_id": row[0], "event_type": row[1],
            "vehicle_id": row[2], "node_id": row[3],
            "payload": payload, "emitted_at": str(row[5]),
        })

    return {
        "_tick_id": "batch", "run_id": run_id,
        "current_routes": current_routes, "solution_metadata": solution_metadata,
        "fleet": fleet, "raw_events": raw_events,
        "anomalies_detected": False, "monitoring_summary": "",
        "classified_events": [], "sla_risk_report": {},
        "rerouting_decision": {}, "dispatch_brief": "",
    }


# ---------------------------------------------------------------------------
# Tick execution
# ---------------------------------------------------------------------------

def run_tick(app) -> dict | None:
    """Execute one telemetry tick. All DB access goes through _db_lock."""
    with _db_lock:
        con = duckdb.connect(DB_PATH)
        # Generate events first so there's something to process
        _generate_events(con, count=3)
        state = load_state(con)
        con.close()

    if state is None:
        return None

    tick_id = str(uuid.uuid4())[:8]
    state["_tick_id"] = tick_id

    tick_start = time.time()
    # Sequential agent pipeline.  We bypass LangGraph here on purpose:
    # LangGraph's BackgroundExecutor + contextvars corruption crashes
    # the second tick with "PyEval_SaveThread: GIL released" on
    # Python 3.11 + Windows.  The graph is linear (monitoring →
    # classification → sla_risk → rerouting → dispatch, with one
    # conditional skip-to-dispatch on no-anomalies), so calling the
    # agent functions directly is equivalent and thread-free.
    import agents.monitoring_agent as _monitoring
    import agents.classification_agent as _classification
    import agents.sla_risk_agent as _sla_risk
    import agents.rerouting_agent as _rerouting
    import agents.dispatch_agent as _dispatch

    state = _monitoring.run(state)
    if state.get("anomalies_detected", False):
        state = _classification.run(state)
        state = _sla_risk.run(state)
        state = _rerouting.run(state)
    state = _dispatch.run(state)
    final_state = state
    tick_duration = time.time() - tick_start

    solver_triggered = False
    solver_duration = 0.0
    decision = final_state.get("rerouting_decision", {})
    if decision.get("should_resolv") and not decision.get("human_approval_required"):
        import subprocess
        solver_start = time.time()
        result = subprocess.run(
            [sys.executable, "assets/optimization/run_solver.py"],
            capture_output=True,
            env={**os.environ, "HERMES_SCENARIO_TAG": "active_disruption"},
        )
        solver_duration = time.time() - solver_start
        solver_triggered = result.returncode == 0

    return {
        "tick_id": tick_id, "run_id": state["run_id"],
        "event_count": len(state["raw_events"]),
        "pipeline_duration": tick_duration,
        "solver_triggered": solver_triggered,
        "solver_duration": solver_duration,
        "anomalies": final_state.get("anomalies_detected", False),
        "sla_score": final_state.get("sla_risk_report", {}).get("sla_risk_score", 0),
        "strategy": decision.get("strategy", "none"),
        "final_state": final_state,
    }


# ---------------------------------------------------------------------------
# Fleet state reader
# ---------------------------------------------------------------------------

def read_fleet_state(_, run_id: str) -> list[dict]:
    """Read current fleet metrics from DB for the right panel.

    On Windows, DuckDB occasionally holds the file lock for a few
    hundred ms after con.close() returns (the previous tick's
    dispatch-agent write or solver subprocess can leave a dangling
    lock).  Retry the read-only open briefly before giving up so a
    transient lock doesn't kill the daemon.
    """
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            with _db_lock:
                con = duckdb.connect(DB_PATH, read_only=True)
                try:
                    rows = con.execute("""
                    SELECT
                        f.vehicle_id,
                        COUNT(rs.node_id) FILTER (WHERE rs.node_id != 0) AS customer_stops,
                        COALESCE(SUM(n.demand_units), 0) AS demand_served,
                        f.capacity_units,
                        COALESCE(MAX(rs.departure_time) - MIN(rs.arrival_time), 0) AS active_min,
                        f.max_shift_min
                    FROM fleet f
                    LEFT JOIN route_solutions rs ON f.vehicle_id = rs.vehicle_id AND rs.run_id = ?
                    LEFT JOIN nodes n ON rs.node_id = n.node_id
                    GROUP BY f.vehicle_id, f.capacity_units, f.max_shift_min
                    ORDER BY f.vehicle_id
                """, [run_id]).fetchall()
                finally:
                    con.close()
            return [
                {
                    "vehicle_id": r[0],
                    "stops": r[1],
                    "demand": r[2],
                    "capacity": r[3],
                    "load_pct": round(r[2] / r[3] * 100) if r[3] > 0 else 0,
                    "active_min": int(r[4]),
                    "shift_pct": round(r[4] / r[5] * 100) if r[5] > 0 else 0,
                }
                for r in rows
            ]
        except duckdb.IOException as e:
            last_err = e
            time.sleep(0.3)
    # All retries exhausted — return last known good state, but log once.
    print(f"  [Telemetry] read_fleet_state failed: {last_err}", file=sys.stderr)
    return []

    return [
        {
            "vehicle_id": r[0],
            "stops": r[1],
            "demand": r[2],
            "capacity": r[3],
            "load_pct": round(r[2] / r[3] * 100) if r[3] > 0 else 0,
            "active_min": int(r[4]),
            "shift_pct": round(r[4] / r[5] * 100) if r[5] > 0 else 0,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Rich UI builder
# ---------------------------------------------------------------------------

def build_ui():
    """Build the Rich three-panel layout."""
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.text import Text

    layout = Layout()

    # Split into header + body
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
    )

    # Split body into left (agent log) + right (metrics)
    layout["body"].split_row(
        Layout(name="agents", ratio=3),
        Layout(name="metrics", ratio=2),
    )

    # Header
    layout["header"].update(Panel(
        Text("HERMES MISSION CONTROL  |  SYSTEM STATUS: ONLINE  |  Waiting for first tick...",
             style="bold white on dark_blue"),
        style="dark_blue",
    ))

    # Agent log panel
    layout["agents"].update(Panel(
        Text("Agent executions will appear here...", style="dim"),
        title="[bold cyan]Agent Executions & Reasoning[/]",
        border_style="cyan",
    ))

    # Metrics panel
    layout["metrics"].update(Panel(
        Text("Fleet metrics will appear here...", style="dim"),
        title="[bold green]Fleet State Metrics[/]",
        border_style="green",
    ))

    return layout


def render_tick(layout, result: dict, tick_count: int, resolver_count: int,
                agent_log_lines: list, fleet_state: list[dict]):
    """Update the Rich layout with latest tick data."""
    from rich.panel import Panel
    from rich.text import Text
    from rich.table import Table

    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

    # --- Header ---
    status = "ONLINE" if not result.get("anomalies") else "ANOMALIES DETECTED"
    sla_score = result.get("sla_score", 0)
    header_text = (
        f"HERMES MISSION CONTROL  |  {status}  |  "
        f"TICK: #{tick_count}  |  {ts} UTC  |  "
        f"RUN: {result['run_id'][:12]}  |  "
        f"SLA: {sla_score:.2f}  |  "
        f"RESOLVES: {resolver_count}  |  "
        f"Pipeline: {result['pipeline_duration']:.1f}s"
    )
    layout["header"].update(Panel(
        Text(header_text, style="bold white on dark_blue"),
        style="dark_blue",
    ))

    # --- Agent log (left panel) ---
    # Add new lines for this tick
    final = result.get("final_state", {})

    # Monitoring
    anomalies = final.get("anomalies_detected", False)
    summary = final.get("monitoring_summary", "")
    agent_log_lines.append(
        f"[{ts}] [bold cyan]MonitoringAgent[/] -> "
        f"{'anomalies' if anomalies else 'nominal'}: {summary}"
    )

    # Classification
    classified = final.get("classified_events", [])
    if classified:
        counts = {}
        for e in classified:
            s = e.get("severity", "?")
            counts[s] = counts.get(s, 0) + 1
        count_str = ", ".join(f"{s}={n}" for s, n in sorted(counts.items()))
        agent_log_lines.append(
            f"[{ts}] [bold magenta]ClassificationAgent[/] -> "
            f"{len(classified)} events: {count_str}"
        )

    # SLA Risk
    sla = final.get("sla_risk_report", {})
    if sla:
        agent_log_lines.append(
            f"[{ts}] [bold yellow]SLARiskAgent[/] -> "
            f"score {sla.get('sla_risk_score', 0):.2f} ({sla.get('overall_risk_level', '?')})"
        )

    # Rerouting
    decision = final.get("rerouting_decision", {})
    if decision:
        flag = "RESOLV TRIGGERED" if decision.get("should_resolv") else "hold"
        agent_log_lines.append(
            f"[{ts}] [bold blue]ReroutingAgent[/] -> "
            f"{flag}, strategy={decision.get('strategy', '?')}, "
            f"urgency={decision.get('urgency', '?')}"
        )

    # Solver
    if result.get("solver_triggered"):
        agent_log_lines.append(
            f"[{ts}] [bold green]OR-Tools Solver[/] -> "
            f"re-optimized in {result['solver_duration']:.1f}s"
        )

    # Dispatch
    brief = final.get("dispatch_brief", "")
    if brief:
        # Extract STATUS from brief
        status_val = "UNKNOWN"
        for i, line in enumerate(brief.split("\n")):
            if line.strip().upper() == "STATUS" and i + 1 < len(brief.split("\n")):
                status_val = brief.split("\n")[i + 1].strip()
                break
        agent_log_lines.append(
            f"[{ts}] [bold white]DispatchAgent[/] -> "
            f"brief generated, status: {status_val}"
        )

    # Keep last 40 lines, with word wrapping
    display_lines = agent_log_lines[-40:]
    log_text = Text(no_wrap=False)
    for line in display_lines:
        log_text.append(line + "\n")

    layout["agents"].update(Panel(
        log_text,
        title="[bold cyan]Agent Executions & Reasoning[/]",
        border_style="cyan",
    ))

    # --- Fleet metrics (right panel) ---
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Vehicle", style="bold", width=8)
    table.add_column("Stops", justify="right", width=6)
    table.add_column("Load %", justify="right", width=8)
    table.add_column("Shift %", justify="right", width=8)
    table.add_column("Status", width=10)

    for v in fleet_state:
        # Status tag
        if v["stops"] == 0:
            status = "[dim]IDLE[/]"
        elif v["load_pct"] > 85 or v["shift_pct"] > 80:
            status = "[red]DELAYED[/]"
        else:
            status = "[green]ACTIVE[/]"

        # Progress bars
        load_bar = "■" * (v["load_pct"] // 10) + "□" * (10 - v["load_pct"] // 10)
        shift_bar = "■" * (v["shift_pct"] // 10) + "□" * (10 - v["shift_pct"] // 10)

        table.add_row(
            v["vehicle_id"],
            str(v["stops"]),
            f"{v['load_pct']}% {load_bar}",
            f"{v['shift_pct']}% {shift_bar}",
            status,
        )

    # Performance section
    perf_text = Text()
    perf_text.append(f"\nPipeline Latency: ", style="bold")
    perf_text.append(f"{result['pipeline_duration']:.1f}s\n")
    perf_text.append(f"SLA Score: ", style="bold")
    score = result.get("sla_score", 0)
    score_style = "red" if score >= 0.5 else "yellow" if score >= 0.2 else "green"
    perf_text.append(f"{score:.2f}\n", style=score_style)
    if result.get("solver_triggered"):
        perf_text.append(f"Solver Time: ", style="bold")
        perf_text.append(f"{result['solver_duration']:.1f}s\n")
        perf_text.append(f"Scenario: ", style="bold")
        perf_text.append("active_disruption\n", style="bold red")

    from rich.console import Group
    metrics_content = Group(table, perf_text)

    layout["metrics"].update(Panel(
        metrics_content,
        title="[bold green]Fleet State Metrics[/]",
        border_style="green",
    ))


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _locked_query(sql: str, params: list | None = None) -> list:
    """Execute a read query under the DB lock. Returns rows."""
    with _db_lock:
        con = duckdb.connect(DB_PATH, read_only=True)
        rows = con.execute(sql, params or []).fetchall()
        con.close()
    return rows


def main():
    from rich.console import Console

    console = Console()
    layout = build_ui()
    # No LangGraph compilation here — see run_tick() for rationale.
    app = None

    tick_count = 0
    resolver_count = 0
    agent_log_lines: list[str] = []
    fleet_state: list[dict] = []

    # Get initial run_id
    init_rows = _locked_query(
        "SELECT run_id FROM solution_metadata ORDER BY created_at DESC LIMIT 1"
    )
    current_run_id = init_rows[0][0] if init_rows else ""

    # Main-thread redraw: Rich Live (any mode) crashes on Python 3.11
    # + Windows because its background render thread hits
    # "PyEval_SaveThread: GIL released" in threading.wait.  We render
    # the same multi-panel layout in the main thread by clearing the
    # screen with ANSI codes and reprinting the layout.  Visually
    # identical to Rich Live, but no background threads.
    while _running:
        tick_start = time.time()

        try:
            # run_tick acquires _db_lock internally for all DB ops
            result = run_tick(app)
        except Exception as e:
            agent_log_lines.append(f"[ERROR] Tick failed: {e}")
            result = None

        if result is not None:
            tick_count += 1
            if result["solver_triggered"]:
                resolver_count += 1
            current_run_id = result["run_id"]

            # Read fleet state under lock
            fleet_state = read_fleet_state(None, current_run_id)

            render_tick(layout, result, tick_count, resolver_count,
                        agent_log_lines, fleet_state)
        else:
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            from rich.text import Text
            from rich.panel import Panel
            idle_text = (
                f"HERMES MISSION CONTROL  |  SYSTEM STATUS: ONLINE  |  "
                f"TICK: #{tick_count}  |  "
                f"Last active: {ts} UTC  |  Waiting for events..."
            )
            layout["header"].update(
                Panel(
                    Text(idle_text, style="bold white on dark_blue"),
                    style="dark_blue",
                )
            )

        # CSI 2J = clear screen, CSI H = cursor home
        # Reprint the layout in the main thread.
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.flush()
        console.print(layout)

        elapsed = time.time() - tick_start
        sleep_time = max(0, TICK_INTERVAL_S - elapsed)
        if sleep_time > 0 and _running:
            time.sleep(sleep_time)

        # Force GC between ticks — LangGraph's thread pool leaves
        # dangling thread state on Windows + Python 3.11, which
        # corrupts the next iteration.  Collecting cleans it up.
        import gc
        gc.collect()

    console.print(f"\n[bold]Telemetry stopped.[/] {tick_count} ticks, {resolver_count} re-solves.")


if __name__ == "__main__":
    main()
