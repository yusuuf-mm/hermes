"""
cvrptw_solver.py
----------------
Solves the Capacitated Vehicle Routing Problem with Time Windows (CVRPTW)
using Google OR-Tools' Routing Library (not raw CP-SAT — the Routing Library
is purpose-built for VRP and handles the arc/time/capacity callbacks natively).

Mathematical model (from Phase 1):
  min  Σ_k Σ_(i,j)∈A  c_ij · x_ijk
  s.t. C1-C7 (flow, capacity, time windows, shift limits)

Inputs  : cvrptw_input view  (nodes + demands + time windows)
          arc_costs table    (travel times and distances)
          fleet table        (capacity, shift limits)
Outputs : route_solutions    (one row per stop per vehicle)
          solution_metadata  (KPIs and solver status)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import duckdb
from ortools.constraint_solver import pywrapcp, routing_enums_pb2


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Node:
    node_id:      int
    name:         str
    tw_open:      int    # minutes from midnight
    tw_close:     int
    service_min:  int
    demand_units: int
    is_depot:     bool


@dataclass
class Vehicle:
    vehicle_id:    str
    capacity_units: int
    max_shift_min:  int


@dataclass
class SolverInput:
    nodes:        list[Node]
    vehicles:     list[Vehicle]
    time_matrix:  list[list[int]]   # integer minutes (OR-Tools requires int)
    dist_matrix:  list[list[int]]   # integer km × 100 (scaled)
    depot_index:  int = 0


@dataclass
class RouteStop:
    vehicle_id:    str
    stop_seq:      int
    node_id:       int
    arrival_time:  float
    departure_time: float


@dataclass
class SolverOutput:
    run_id:               str
    status:               str
    total_cost_km:        float
    vehicles_used:        int
    orders_served:        int
    constraint_violations: int
    solve_time_s:         float
    routes:               list[RouteStop] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_solver_input(con: duckdb.DuckDBPyConnection) -> SolverInput:
    """Pull all required data from DuckDB and build the SolverInput."""

    # Nodes from the clean transform view
    node_rows = con.execute("""
        SELECT node_id, name, tw_open, tw_close, service_min,
               total_demand, is_depot
        FROM cvrptw_input
        ORDER BY is_depot DESC, node_id ASC
    """).fetchall()

    nodes = [
        Node(
            node_id=r[0], name=r[1], tw_open=r[2], tw_close=r[3],
            service_min=r[4], demand_units=r[5], is_depot=bool(r[6])
        )
        for r in node_rows
    ]

    # Fleet
    fleet_rows = con.execute(
        "SELECT vehicle_id, capacity_units, max_shift_min FROM fleet"
    ).fetchall()
    vehicles = [Vehicle(*r) for r in fleet_rows]

    # Arc costs — build index map for fast lookup
    node_id_to_idx = {n.node_id: i for i, n in enumerate(nodes)}
    n = len(nodes)

    time_matrix = [[0] * n for _ in range(n)]
    dist_matrix = [[0] * n for _ in range(n)]

    arc_rows = con.execute(
        "SELECT from_node, to_node, cost_km, travel_min FROM arc_costs"
    ).fetchall()

    for from_id, to_id, cost_km, travel_min in arc_rows:
        if from_id in node_id_to_idx and to_id in node_id_to_idx:
            i = node_id_to_idx[from_id]
            j = node_id_to_idx[to_id]
            # OR-Tools requires integer callbacks — scale and cast
            time_matrix[i][j] = int(travel_min)
            dist_matrix[i][j] = int(cost_km * 100)  # store as cm to preserve 2dp

    depot_index = node_id_to_idx[0]  # node_id 0 is always the depot

    return SolverInput(
        nodes=nodes,
        vehicles=vehicles,
        time_matrix=time_matrix,
        dist_matrix=dist_matrix,
        depot_index=depot_index,
    )


# ---------------------------------------------------------------------------
# Core solver
# ---------------------------------------------------------------------------

def solve(inp: SolverInput, time_limit_s: int = 60) -> SolverOutput:
    """
    Build and solve the CVRPTW model.
    Returns a SolverOutput regardless of status (OPTIMAL / FEASIBLE / INFEASIBLE).
    """
    run_id    = f"RUN-{uuid.uuid4().hex[:8].upper()}"
    t_start   = time.time()
    num_nodes = len(inp.nodes)
    num_vehs  = len(inp.vehicles)

    # -- Manager & Routing model -------------------------------------------
    manager = pywrapcp.RoutingIndexManager(
        num_nodes, num_vehs, inp.depot_index
    )
    routing = pywrapcp.RoutingModel(manager)

    # -- Distance callback (objective) -------------------------------------
    def distance_callback(from_idx, to_idx):
        i = manager.IndexToNode(from_idx)
        j = manager.IndexToNode(to_idx)
        return inp.dist_matrix[i][j]

    transit_callback_idx = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_idx)

    # -- Time callback + time windows (C4, C5) -----------------------------
    def time_callback(from_idx, to_idx):
        i = manager.IndexToNode(from_idx)
        j = manager.IndexToNode(to_idx)
        return inp.time_matrix[i][j] + inp.nodes[i].service_min

    time_callback_idx = routing.RegisterTransitCallback(time_callback)

    # Horizon must cover the latest tw_close across all nodes
    horizon = max(n.tw_close for n in inp.nodes) + 60

    routing.AddDimension(
        time_callback_idx,
        slack_max=120,          # max waiting time at a node (minutes)
        capacity=horizon,       # absolute time ceiling for the dimension
        fix_start_cumul_to_zero=False,
        name="Time",
    )
    time_dim = routing.GetDimensionOrDie("Time")

    for node_idx, node in enumerate(inp.nodes):
        if node.is_depot:
            continue
        routing_idx = manager.NodeToIndex(node_idx)
        time_dim.CumulVar(routing_idx).SetRange(node.tw_open, node.tw_close)

    # Depot time window  (C1)
    for v in range(num_vehs):
        routing.AddVariableMinimizedByFinalizer(
            time_dim.CumulVar(routing.Start(v))
        )
        routing.AddVariableMinimizedByFinalizer(
            time_dim.CumulVar(routing.End(v))
        )

    # -- Capacity constraint (C3) ------------------------------------------
    def demand_callback(from_idx):
        i = manager.IndexToNode(from_idx)
        return inp.nodes[i].demand_units

    demand_callback_idx = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_callback_idx,
        slack_max=0,
        vehicle_capacities=[v.capacity_units for v in inp.vehicles],
        fix_start_cumul_to_zero=True,
        name="Capacity",
    )

    # -- Search parameters -------------------------------------------------
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_params.time_limit.seconds = time_limit_s
    search_params.log_search = False

    # -- Solve -------------------------------------------------------------
    solution = routing.SolveWithParameters(search_params)
    solve_time = round(time.time() - t_start, 3)

    # -- Extract solution --------------------------------------------------
    status_map = {
        0: "NOT_SOLVED", 1: "SUCCESS", 2: "FAIL",
        3: "FAIL_TIMEOUT", 4: "INVALID",
    }
    status = status_map.get(routing.status(), "UNKNOWN")

    if solution is None:
        return SolverOutput(
            run_id=run_id, status="INFEASIBLE",
            total_cost_km=0, vehicles_used=0, orders_served=0,
            constraint_violations=1, solve_time_s=solve_time,
        )

    routes:        list[RouteStop] = []
    total_dist_cm: int             = 0
    vehicles_used: int             = 0
    nodes_visited: set[int]        = set()

    for v_idx in range(num_vehs):
        idx = routing.Start(v_idx)
        stop_seq = 0
        route_stops: list[RouteStop] = []

        while not routing.IsEnd(idx):
            node_idx    = manager.IndexToNode(idx)
            time_var    = time_dim.CumulVar(idx)
            arrival     = solution.Min(time_var)
            departure   = arrival + inp.nodes[node_idx].service_min

            route_stops.append(RouteStop(
                vehicle_id    = inp.vehicles[v_idx].vehicle_id,
                stop_seq      = stop_seq,
                node_id       = inp.nodes[node_idx].node_id,
                arrival_time  = float(arrival),
                departure_time= float(departure),
            ))

            if not inp.nodes[node_idx].is_depot:
                nodes_visited.add(inp.nodes[node_idx].node_id)

            total_dist_cm += routing.GetArcCostForVehicle(
                idx, solution.Value(routing.NextVar(idx)), v_idx
            )
            idx      = solution.Value(routing.NextVar(idx))
            stop_seq += 1

        # add return-to-depot stop
        node_idx = manager.IndexToNode(idx)
        time_var = time_dim.CumulVar(idx)
        route_stops.append(RouteStop(
            vehicle_id    = inp.vehicles[v_idx].vehicle_id,
            stop_seq      = stop_seq,
            node_id       = inp.nodes[node_idx].node_id,
            arrival_time  = float(solution.Min(time_var)),
            departure_time= float(solution.Min(time_var)),
        ))

        # only count vehicle if it made at least one customer stop
        customer_stops = [s for s in route_stops if s.node_id != 0]
        if customer_stops:
            vehicles_used += 1
            routes.extend(route_stops)

    total_cost_km = round(total_dist_cm / 100, 2)

    # -- Post-solve capacity validation ------------------------------------
    constraint_violations = 0
    node_demand = {n.node_id: n.demand_units for n in inp.nodes}
    vehicle_cap = {v.vehicle_id: v.capacity_units for v in inp.vehicles}

    vehicle_loads: dict[str, int] = {}
    for stop in routes:
        if stop.node_id == 0:
            continue
        vid = stop.vehicle_id
        vehicle_loads[vid] = vehicle_loads.get(vid, 0) + node_demand[stop.node_id]

    for vid, load in vehicle_loads.items():
        cap = vehicle_cap.get(vid, 0)
        if load > cap:
            constraint_violations += 1

    return SolverOutput(
        run_id                = run_id,
        status                = status,
        total_cost_km         = total_cost_km,
        vehicles_used         = vehicles_used,
        orders_served         = len(nodes_visited),
        constraint_violations = constraint_violations,
        solve_time_s          = solve_time,
        routes                = routes,
    )
