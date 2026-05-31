""" @bruin
name: hermes.optimization.run_solver
type: python

depends:
  - hermes.quality.check_orders_freshness
  - hermes.quality.check_demand_positive
  - hermes.quality.check_time_windows_valid

description: >
  Executes the CVRPTW optimization solver using Google OR-Tools.
  Depends on all three quality checks passing. Writes route_solutions
  and solution_metadata to DuckDB.
@bruin """

import os
import sys

# Ensure project root is on the path when run via Bruin
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import duckdb

from optimization.cvrptw_solver import load_solver_input, solve
from optimization.solution_writer import write_solution


DB_PATH       = os.environ.get("HERMES_DB_PATH", "hermes.duckdb")
TIME_LIMIT_S  = int(os.environ.get("SOLVER_TIME_LIMIT_S", "60"))


def run():
    print("=" * 60)
    print("HERMES — CVRPTW Solver")
    print("=" * 60)

    con = duckdb.connect(DB_PATH)

    # Execute the transform view so the solver reads clean data
    with open("assets/transforms/build_cvrptw_input.sql") as f:
        con.execute(f.read())

    print("Loading solver input from DuckDB...")
    inp = load_solver_input(con)
    print(f"  Nodes    : {len(inp.nodes)} (1 depot + {len(inp.nodes)-1} customers)")
    print(f"  Vehicles : {len(inp.vehicles)}")
    print(f"  Time limit: {TIME_LIMIT_S}s")

    print("\nRunning OR-Tools CVRPTW solver...")
    output = solve(inp, time_limit_s=TIME_LIMIT_S)

    print(f"\nSolver finished — status: {output.status}")
    write_solution(con, output)

    con.close()
    print("\nDone.")

    # Exit non-zero if solver failed (Bruin will mark asset as failed)
    if output.status in ("INFEASIBLE", "NOT_SOLVED", "FAIL"):
        sys.exit(1)


if __name__ == "__main__":
    run()
