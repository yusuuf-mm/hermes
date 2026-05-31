""" @bruin
name: hermes.ingestion.seed
type: python

description: >
  Seeds the HERMES DuckDB database with synthetic Lagos metro logistics data.
  Generates 26 nodes (1 depot + 25 customers), 5 vehicles, a full arc-cost
  matrix, and 30 daily orders. Also scaffolds empty event and solution tables.
@bruin """

import math
import random
import duckdb
import os

random.seed(42)

DB_PATH = os.environ.get("HERMES_DB_PATH", "hermes.duckdb")

# ---------------------------------------------------------------------------
# Node definitions  (lat/lon roughly centred on Lagos Island)
# ---------------------------------------------------------------------------
DEPOT = {
    "node_id": 0,
    "name": "Central Depot — Lagos Island",
    "lat": 6.4541,
    "lon": 3.3947,
    "tw_open": 360,    # 06:00 in minutes from midnight
    "tw_close": 1080,  # 18:00
    "service_min": 0,
    "demand_units": 0,
    "is_depot": True,
}

CUSTOMERS = [
    # (name, lat, lon, tw_open, tw_close, service_min, demand_units)
    ("Ikeja Warehouse",         6.5944, 3.3378, 480, 720,  15, 12),
    ("Victoria Island Hub",     6.4281, 3.4219, 540, 780,  10,  8),
    ("Lekki Phase 1",           6.4474, 3.5396, 480, 900,  12, 15),
    ("Surulere Depot",          6.5059, 3.3554, 600, 840,  10, 10),
    ("Yaba Distribution",       6.5009, 3.3794, 480, 720,  15, 20),
    ("Apapa Port Gate",         6.4490, 3.3566, 420, 660,  20, 25),
    ("Ojota Terminal",          6.5756, 3.3817, 540, 780,  10,  9),
    ("Ikorodu Road Stop",       6.5496, 3.3614, 480, 840,  12, 11),
    ("Maryland Mall",           6.5631, 3.3639, 600, 900,  10, 14),
    ("Gbagada Estate",          6.5422, 3.3803, 540, 780,  15, 18),
    ("Ajah Junction",           6.4683, 3.5787, 480, 840,  20, 22),
    ("Sangotedo",               6.4389, 3.6129, 600, 960,  15, 16),
    ("Badore Road",             6.4583, 3.6264, 540, 900,  10,  7),
    ("Oshodi Interchange",      6.5557, 3.3441, 420, 660,  15, 13),
    ("Agege Market",            6.6204, 3.3213, 480, 720,  20, 19),
    ("Mushin Centre",           6.5214, 3.3558, 540, 780,  10, 21),
    ("Orile Iganmu",            6.4715, 3.3468, 480, 840,  12,  6),
    ("Amuwo Odofin",            6.4607, 3.3226, 540, 900,  15, 17),
    ("Festac Town Gate",        6.4617, 3.2831, 600, 960,  20, 23),
    ("Alimosho Express",        6.6072, 3.2669, 480, 720,  15, 11),
    ("Egbeda Junction",         6.5922, 3.2933, 540, 840,  10,  9),
    ("Iyana Ipaja",             6.6139, 3.2719, 480, 900,  12, 14),
    ("Mile 2 Stop",             6.4722, 3.3108, 600, 840,  10, 16),
    ("Ijora Badia",             6.4691, 3.3680, 540, 780,  15, 12),
    ("CMS Bus Stop",            6.4541, 3.3947, 480, 720,  10,  8),
]

FLEET = [
    {"vehicle_id": f"VH-{i:03d}", "capacity_units": 100,
     "max_shift_min": 480, "depot_id": 0}
    for i in range(1, 6)
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def travel_time_min(dist_km: float, avg_speed_kmh: float = 25.0) -> float:
    """Estimate travel time in minutes. Lagos avg speed ~25 km/h."""
    return (dist_km / avg_speed_kmh) * 60


# ---------------------------------------------------------------------------
# Main seeding routine
# ---------------------------------------------------------------------------

def seed(db_path: str = DB_PATH):
    con = duckdb.connect(db_path)

    # -- nodes ---------------------------------------------------------------
    con.execute("DROP TABLE IF EXISTS nodes")
    con.execute("""
        CREATE TABLE nodes (
            node_id      INTEGER PRIMARY KEY,
            name         VARCHAR,
            lat          DOUBLE,
            lon          DOUBLE,
            tw_open      INTEGER,   -- minutes from midnight
            tw_close     INTEGER,
            service_min  INTEGER,
            demand_units INTEGER,
            is_depot     BOOLEAN
        )
    """)

    all_nodes = [DEPOT]
    for i, (name, lat, lon, tw_o, tw_c, svc, dem) in enumerate(CUSTOMERS, start=1):
        all_nodes.append({
            "node_id": i, "name": name, "lat": lat, "lon": lon,
            "tw_open": tw_o, "tw_close": tw_c,
            "service_min": svc, "demand_units": dem, "is_depot": False,
        })

    con.executemany(
        "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(n["node_id"], n["name"], n["lat"], n["lon"],
          n["tw_open"], n["tw_close"], n["service_min"],
          n["demand_units"], n["is_depot"]) for n in all_nodes],
    )
    print(f"  nodes       : {len(all_nodes)} rows")

    # -- fleet ---------------------------------------------------------------
    con.execute("DROP TABLE IF EXISTS fleet")
    con.execute("""
        CREATE TABLE fleet (
            vehicle_id     VARCHAR PRIMARY KEY,
            capacity_units INTEGER,
            max_shift_min  INTEGER,
            depot_id       INTEGER
        )
    """)
    con.executemany(
        "INSERT INTO fleet VALUES (?, ?, ?, ?)",
        [(v["vehicle_id"], v["capacity_units"],
          v["max_shift_min"], v["depot_id"]) for v in FLEET],
    )
    print(f"  fleet       : {len(FLEET)} rows")

    # -- arc_costs -----------------------------------------------------------
    con.execute("DROP TABLE IF EXISTS arc_costs")
    con.execute("""
        CREATE TABLE arc_costs (
            from_node  INTEGER,
            to_node    INTEGER,
            cost_km    DOUBLE,
            travel_min DOUBLE,
            PRIMARY KEY (from_node, to_node)
        )
    """)

    road_factor = 1.35   # straight-line to road-distance multiplier
    arc_rows = []
    for i, ni in enumerate(all_nodes):
        for j, nj in enumerate(all_nodes):
            if i == j:
                continue
            dist = haversine_km(ni["lat"], ni["lon"], nj["lat"], nj["lon"]) * road_factor
            t    = travel_time_min(dist)
            arc_rows.append((ni["node_id"], nj["node_id"], round(dist, 4), round(t, 2)))

    con.executemany("INSERT INTO arc_costs VALUES (?, ?, ?, ?)", arc_rows)
    print(f"  arc_costs   : {len(arc_rows)} rows")

    # -- daily_orders --------------------------------------------------------
    con.execute("DROP TABLE IF EXISTS daily_orders")
    con.execute("""
        CREATE TABLE daily_orders (
            order_id    VARCHAR PRIMARY KEY,
            node_id     INTEGER,
            demand_units INTEGER,
            order_date  DATE,
            status      VARCHAR DEFAULT 'pending'
        )
    """)

    customer_ids = [n["node_id"] for n in all_nodes if not n["is_depot"]]
    orders = []
    for i in range(1, 31):
        nid = random.choice(customer_ids)
        node = next(n for n in all_nodes if n["node_id"] == nid)
        orders.append((
            f"ORD-{i:04d}", nid,
            random.randint(1, min(20, node["demand_units"])),
            "2025-01-27", "pending",
        ))

    con.executemany("INSERT INTO daily_orders VALUES (?, ?, ?, ?, ?)", orders)
    print(f"  daily_orders: {len(orders)} rows")

    # -- raw_events (empty — event simulator will populate) ------------------
    con.execute("DROP TABLE IF EXISTS raw_events")
    con.execute("""
        CREATE TABLE raw_events (
            event_id    VARCHAR PRIMARY KEY,
            event_type  VARCHAR,
            vehicle_id  VARCHAR,
            node_id     INTEGER,
            payload     JSON,
            emitted_at  TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # -- processed_events (empty — agents will populate) ---------------------
    con.execute("DROP TABLE IF EXISTS processed_events")
    con.execute("""
        CREATE TABLE processed_events (
            event_id       VARCHAR PRIMARY KEY,
            severity       VARCHAR,
            category       VARCHAR,
            sla_risk_score DOUBLE,
            action_taken   VARCHAR,
            processed_at   TIMESTAMP DEFAULT current_timestamp
        )
    """)

    # -- route_solutions (empty — solver will populate) ----------------------
    con.execute("DROP TABLE IF EXISTS route_solutions")
    con.execute("""
        CREATE TABLE route_solutions (
            run_id         VARCHAR,
            vehicle_id     VARCHAR,
            stop_seq       INTEGER,
            node_id        INTEGER,
            arrival_time   DOUBLE,
            departure_time DOUBLE,
            PRIMARY KEY (run_id, vehicle_id, stop_seq)
        )
    """)

    # -- solution_metadata ---------------------------------------------------
    con.execute("DROP TABLE IF EXISTS solution_metadata")
    con.execute("""
        CREATE TABLE solution_metadata (
            run_id              VARCHAR PRIMARY KEY,
            total_cost_km       DOUBLE,
            vehicles_used       INTEGER,
            orders_served       INTEGER,
            constraint_violations INTEGER,
            solve_time_s        DOUBLE,
            solver_status       VARCHAR,
            created_at          TIMESTAMP DEFAULT current_timestamp
        )
    """)

    con.close()
    print(f"\n  All tables seeded into: {db_path}")


if __name__ == "__main__":
    print("Seeding HERMES database...")
    seed()
    print("Done.")
