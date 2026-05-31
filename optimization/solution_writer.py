"""
solution_writer.py
------------------
Writes a SolverOutput (routes + metadata) into DuckDB.
Separated from the solver so the writing logic can be tested
independently from the OR model.
"""

from __future__ import annotations

import duckdb
from optimization.cvrptw_solver import SolverOutput


def write_solution(con: duckdb.DuckDBPyConnection, output: SolverOutput) -> None:
    """
    Persist solver output to:
      - route_solutions    (one row per stop)
      - solution_metadata  (one row per run)
    """
    # -- route_solutions --------------------------------------------------
    if output.routes:
        con.executemany(
            """
            INSERT INTO route_solutions
                (run_id, vehicle_id, stop_seq, node_id, arrival_time, departure_time)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    output.run_id,
                    stop.vehicle_id,
                    stop.stop_seq,
                    stop.node_id,
                    stop.arrival_time,
                    stop.departure_time,
                )
                for stop in output.routes
            ],
        )

    # -- solution_metadata ------------------------------------------------
    con.execute(
        """
        INSERT INTO solution_metadata
            (run_id, total_cost_km, vehicles_used, orders_served,
             constraint_violations, solve_time_s, solver_status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            output.run_id,
            output.total_cost_km,
            output.vehicles_used,
            output.orders_served,
            output.constraint_violations,
            output.solve_time_s,
            output.status,
        ),
    )

    print(
        f"  Written run {output.run_id} | "
        f"status={output.status} | "
        f"cost={output.total_cost_km} km | "
        f"vehicles={output.vehicles_used} | "
        f"served={output.orders_served} nodes | "
        f"time={output.solve_time_s}s"
    )
