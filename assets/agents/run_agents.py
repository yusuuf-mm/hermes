""" @bruin
name: hermes.agents.run_agents
type: python

depends:
  - hermes.optimization.run_solver

description: >
  Runs the HERMES five-agent LangGraph system.
  Reads the latest route solution and all unprocessed events from DuckDB.
  Agents: Monitoring → Classification → SLA Risk → Rerouting → Dispatch.
  Writes processed_events and the dispatch brief back to DuckDB.
@bruin """

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import duckdb
from dotenv import load_dotenv

load_dotenv("config/.env" if os.path.exists("config/.env") else ".env",
            override=False)

DB_PATH = os.environ.get("HERMES_DB_PATH", "hermes.duckdb")


# ---------------------------------------------------------------------------
# State loader — reads everything the agents need from DuckDB
# ---------------------------------------------------------------------------

def load_state(con: duckdb.DuckDBPyConnection) -> dict:
    """Build the initial HermesState dict from DuckDB."""

    # Latest solver run
    meta_row = con.execute("""
        SELECT run_id, total_cost_km, vehicles_used, orders_served,
               constraint_violations, solve_time_s, solver_status
        FROM solution_metadata
        ORDER BY created_at DESC
        LIMIT 1
    """).fetchone()

    if not meta_row:
        raise RuntimeError(
            "No solution found in solution_metadata. "
            "Run 'make solve' before running agents."
        )

    run_id = meta_row[0]
    solution_metadata = {
        "run_id":                 meta_row[0],
        "total_cost_km":          meta_row[1],
        "vehicles_used":          meta_row[2],
        "orders_served":          meta_row[3],
        "constraint_violations":  meta_row[4],
        "solve_time_s":           meta_row[5],
        "solver_status":          meta_row[6],
    }

    # Current routes for this run
    route_rows = con.execute("""
        SELECT vehicle_id, stop_seq, node_id, arrival_time, departure_time
        FROM route_solutions
        WHERE run_id = ?
        ORDER BY vehicle_id, stop_seq
    """, [run_id]).fetchall()

    current_routes = [
        {
            "vehicle_id":     r[0],
            "stop_seq":       r[1],
            "node_id":        r[2],
            "arrival_time":   r[3],
            "departure_time": r[4],
        }
        for r in route_rows
    ]

    # Fleet
    fleet_rows = con.execute(
        "SELECT vehicle_id, capacity_units, max_shift_min, depot_id FROM fleet"
    ).fetchall()

    fleet = [
        {
            "vehicle_id":      r[0],
            "capacity_units":  r[1],
            "max_shift_min":   r[2],
            "depot_id":        r[3],
        }
        for r in fleet_rows
    ]

    # Unprocessed raw events (not yet in processed_events)
    event_rows = con.execute("""
        SELECT r.event_id, r.event_type, r.vehicle_id, r.node_id,
               r.payload, r.emitted_at
        FROM raw_events r
        LEFT JOIN processed_events p ON r.event_id = p.event_id
        WHERE p.event_id IS NULL
        ORDER BY r.emitted_at ASC
        LIMIT 50   -- cap per cycle to control prompt size
    """).fetchall()

    raw_events = []
    for row in event_rows:
        payload = row[4]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        raw_events.append({
            "event_id":   row[0],
            "event_type": row[1],
            "vehicle_id": row[2],
            "node_id":    row[3],
            "payload":    payload,
            "emitted_at": str(row[5]),
        })

    return {
        "_tick_id":          "batch",   # overwritten by run_telemetry.py
        "run_id":            run_id,
        "current_routes":    current_routes,
        "solution_metadata": solution_metadata,
        "fleet":             fleet,
        "raw_events":        raw_events,
        # Agent outputs (populated during graph execution)
        "anomalies_detected":  False,
        "monitoring_summary":  "",
        "classified_events":   [],
        "sla_risk_report":     {},
        "rerouting_decision":  {},
        "dispatch_brief":      "",
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run():
    print("=" * 60)
    print("HERMES — Agent System")
    print(f"Started: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 60)

    con = duckdb.connect(DB_PATH)
    state = load_state(con)
    con.close()

    print("\nLoaded state:")
    print(f"  Run ID        : {state['run_id']}")
    print(f"  Route stops   : {len(state['current_routes'])}")
    print(f"  Unprocessed   : {len(state['raw_events'])} events")

    if not state["raw_events"]:
        print("\n  No unprocessed events. Run the event simulator first:")
        print("  make events")
        return

    # Build and run the graph
    from agents.graph import compile_graph
    app = compile_graph()

    print("\nRunning agent graph...\n")
    final_state = app.invoke(state)

    # -- Post-graph: re-invoke solver if Rerouting Agent requested it ------
    decision = final_state.get("rerouting_decision", {})
    if decision.get("should_resolve") and not decision.get("human_approval_required"):
        print("\n[!] Rerouting Agent triggered re-optimisation.")
        print("   Invoking solver...\n")
        import subprocess
        result = subprocess.run(
            [sys.executable, "assets/optimization/run_solver.py"],
            capture_output=False,
            env={**os.environ, "HERMES_SCENARIO_TAG": "active_disruption"},
        )
        if result.returncode == 0:
            print("   Re-optimisation complete.")
        else:
            print("   Re-optimisation failed — check solver logs.")

    elif decision.get("should_resolve") and decision.get("human_approval_required"):
        print("\n[!] Re-optimisation recommended but REQUIRES HUMAN APPROVAL.")
        print("   See dispatch brief above. No automatic re-solve triggered.")

    print("\nAgent cycle complete.")


if __name__ == "__main__":
    run()
