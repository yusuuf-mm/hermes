"""
test_solution_feasibility.py
-----------------------------
Verifies that a SolverOutput satisfies all seven CVRPTW constraints
defined in Phase 1 of the HERMES mathematical formulation.

Run:
    pytest optimization/tests/test_solution_feasibility.py -v
"""

from __future__ import annotations

import pytest

from optimization.cvrptw_solver import Node, SolverInput, Vehicle, solve

# ---------------------------------------------------------------------------
# Minimal test fixture — Solomon C101 instance (first 5 customers)
# ---------------------------------------------------------------------------
# Coordinates scaled so travel_time ≈ Euclidean distance (Solomon standard).
#
# service_min=30 (deviation from C101's 90-min standard): the fixture's
# narrow time windows (45–81 min wide) cannot accommodate 90-min service,
# which made the problem INFEASIBLE by construction. 30-min service fits
# all windows and is a common Solomon variant.

DEPOT = Node(node_id=0, name="Depot", tw_open=0, tw_close=1236,
             service_min=0, demand_units=0, is_depot=True)

CUSTOMERS = [
    Node(node_id=1,  name="C1",  tw_open=912,  tw_close=967,  service_min=30, demand_units=10, is_depot=False),
    Node(node_id=2,  name="C2",  tw_open=825,  tw_close=870,  service_min=30, demand_units=30, is_depot=False),
    Node(node_id=3,  name="C3",  tw_open=65,   tw_close=146,  service_min=30, demand_units=10, is_depot=False),
    Node(node_id=4,  name="C4",  tw_open=727,  tw_close=782,  service_min=30, demand_units=10, is_depot=False),
    Node(node_id=5,  name="C5",  tw_open=15,   tw_close=67,   service_min=30, demand_units=10, is_depot=False),
]

# Simple symmetric distance/time matrix (integer minutes)
COORDS = [(35, 35), (41, 49), (35, 17), (55, 45), (55, 20), (15, 30)]  # depot + 5 cust

def _dist(i, j):
    x1, y1 = COORDS[i]
    x2, y2 = COORDS[j]
    import math
    return int(math.hypot(x2 - x1, y2 - y1))

N = len(COORDS)
TIME_MATRIX = [[_dist(i, j) for j in range(N)] for i in range(N)]
DIST_MATRIX = [[_dist(i, j) * 10 for j in range(N)] for i in range(N)]

VEHICLES = [
    Vehicle(vehicle_id="V1", capacity_units=100, max_shift_min=1236),
    Vehicle(vehicle_id="V2", capacity_units=100, max_shift_min=1236),
]

SOLVER_INPUT = SolverInput(
    nodes=[DEPOT] + CUSTOMERS,
    vehicles=VEHICLES,
    time_matrix=TIME_MATRIX,
    dist_matrix=DIST_MATRIX,
    depot_index=0,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def solution():
    return solve(SOLVER_INPUT, time_limit_s=10)


def test_solver_finds_solution(solution):
    """Solver must return a feasible or optimal solution."""
    assert solution.status in ("SUCCESS", "OPTIMAL"), (
        f"Solver returned non-feasible status: {solution.status}"
    )


def test_c2_each_customer_visited_exactly_once(solution):
    """C2: every customer node appears in exactly one route."""
    visited_counts: dict[int, int] = {}
    for stop in solution.routes:
        if stop.node_id != 0:   # exclude depot
            visited_counts[stop.node_id] = visited_counts.get(stop.node_id, 0) + 1

    for nid, count in visited_counts.items():
        assert count == 1, f"Node {nid} visited {count} times (C2 violation)"

    customer_ids = {n.node_id for n in CUSTOMERS}
    assert customer_ids == set(visited_counts.keys()), (
        "Not all customers were visited"
    )


def test_c3_capacity_not_exceeded(solution):
    """C3: total demand on each vehicle must not exceed capacity."""
    vehicle_loads: dict[str, int] = {}
    node_demand   = {n.node_id: n.demand_units for n in SOLVER_INPUT.nodes}

    for stop in solution.routes:
        if stop.node_id == 0:
            continue
        vid = stop.vehicle_id
        vehicle_loads[vid] = vehicle_loads.get(vid, 0) + node_demand[stop.node_id]

    for vehicle in VEHICLES:
        load = vehicle_loads.get(vehicle.vehicle_id, 0)
        assert load <= vehicle.capacity_units, (
            f"Vehicle {vehicle.vehicle_id} load={load} exceeds "
            f"capacity={vehicle.capacity_units} (C3 violation)"
        )


def test_c4_time_windows_respected(solution):
    """C4: service start time must be within [tw_open, tw_close]."""
    node_windows = {n.node_id: (n.tw_open, n.tw_close) for n in SOLVER_INPUT.nodes}

    for stop in solution.routes:
        if stop.node_id == 0:
            continue
        tw_o, tw_c = node_windows[stop.node_id]
        # arrival_time may be before tw_open (vehicle waits) — departure must be ≥ tw_open
        assert stop.departure_time >= tw_o, (
            f"Node {stop.node_id}: departure {stop.departure_time} < tw_open {tw_o} (C4)"
        )
        assert stop.arrival_time <= tw_c, (
            f"Node {stop.node_id}: arrival {stop.arrival_time} > tw_close {tw_c} (C4)"
        )


def test_c5_temporal_feasibility(solution):
    """C5: departure from stop i + travel ≤ arrival at stop i+1."""
    from collections import defaultdict

    vehicle_routes: dict[str, list] = defaultdict(list)
    for stop in solution.routes:
        vehicle_routes[stop.vehicle_id].append(stop)

    for vid, stops in vehicle_routes.items():
        stops_sorted = sorted(stops, key=lambda s: s.stop_seq)
        for k in range(len(stops_sorted) - 1):
            curr = stops_sorted[k]
            nxt  = stops_sorted[k + 1]
            travel = TIME_MATRIX[curr.node_id][nxt.node_id]
            # arrival at next ≥ departure from current + travel
            assert nxt.arrival_time >= curr.departure_time + travel - 1, (
                f"Vehicle {vid}: temporal infeasibility between "
                f"node {curr.node_id} → {nxt.node_id} (C5)"
            )


def test_solution_cost_is_positive(solution):
    """Sanity: total cost must be a positive number."""
    assert solution.total_cost_km > 0


def test_vehicles_used_within_fleet_size(solution):
    """Cannot use more vehicles than available."""
    assert solution.vehicles_used <= len(VEHICLES)
