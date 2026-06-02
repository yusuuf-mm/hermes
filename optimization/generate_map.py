"""
generate_map.py
---------------
Generates an interactive Folium map of routing solutions.
Reads route_solutions + nodes from DuckDB, draws polylines
colored by vehicle, with FeatureGroup per scenario_tag.
Outputs dashboard/static/routes_map.html.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import duckdb
import folium

# MotherDuck connection when MOTHERDUCK_TOKEN is set, local file otherwise
_token = os.environ.get("MOTHERDUCK_TOKEN")
if _token:
    DB_PATH = f"md:hermes01?motherduck_token={_token}"
else:
    DB_PATH = os.environ.get("HERMES_DB_PATH", "hermes.duckdb")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "../dashboard/public/routes_map.html")

# Colour palette per vehicle (up to 8 vehicles)
VEHICLE_COLORS = [
    "#e6194b",  # red
    "#3cb44b",  # green
    "#4363d8",  # blue
    "#f58231",  # orange
    "#911eb4",  # purple
    "#42d4f4",  # cyan
    "#f032e6",  # magenta
    "#bfef45",  # lime
]


def load_route_data(con):
    """Load routes joined with node coordinates and scenario tags."""
    rows = con.execute("""
        SELECT
            sm.scenario_tag,
            rs.run_id,
            rs.vehicle_id,
            rs.stop_seq,
            rs.node_id,
            n.name,
            n.lat,
            n.lon,
            n.is_depot,
            rs.arrival_time,
            rs.departure_time
        FROM route_solutions rs
        JOIN solution_metadata sm ON rs.run_id = sm.run_id
        JOIN nodes n ON rs.node_id = n.node_id
        ORDER BY sm.scenario_tag, rs.run_id, rs.vehicle_id, rs.stop_seq
    """).fetchall()
    return rows


def load_vehicle_ids(con):
    """Get ordered list of vehicle IDs for consistent colour mapping."""
    rows = con.execute("SELECT vehicle_id FROM fleet ORDER BY vehicle_id").fetchall()
    return [r[0] for r in rows]


def build_map(rows, vehicle_ids):
    """Build a Folium map with FeatureGroups per scenario_tag."""
    # Centre on Lagos
    m = folium.Map(location=[6.5244, 3.3792], zoom_start=11, tiles="OpenStreetMap")

    # --- Depot marker (always visible) ----------------------------------
    depot_lat, depot_lon = None, None
    for r in rows:
        if r[8]:  # is_depot
            depot_lat, depot_lon = r[6], r[7]
            break

    if depot_lat:
        folium.Marker(
            location=[depot_lat, depot_lon],
            popup="Central Depot - Lagos Island",
            icon=folium.Icon(color="red", icon="warehouse", prefix="fa"),
        ).add_to(m)

    # --- Customer node markers (always visible) -------------------------
    seen_nodes = set()
    for r in rows:
        node_id, name, lat, lon, is_depot = r[4], r[5], r[6], r[7], r[8]
        if is_depot or node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)
        folium.CircleMarker(
            location=[lat, lon],
            radius=5,
            color="#333333",
            fill=True,
            fill_opacity=0.7,
            popup=f"{name} (Node {node_id})",
        ).add_to(m)

    # --- Route lines per scenario ---------------------------------------
    # Group rows by (scenario_tag, run_id, vehicle_id)
    from collections import defaultdict
    routes = defaultdict(list)
    for r in rows:
        key = (r[0], r[1], r[2])  # scenario_tag, run_id, vehicle_id
        routes[key].append(r)

    # Create one FeatureGroup per scenario_tag
    scenario_groups = {}
    for (scenario_tag, run_id, vehicle_id), stops in routes.items():
        if scenario_tag not in scenario_groups:
            fg = folium.FeatureGroup(name=f"Scenario: {scenario_tag}")
            scenario_groups[scenario_tag] = fg

        fg = scenario_groups[scenario_tag]

        # Colour by vehicle index
        try:
            v_idx = vehicle_ids.index(vehicle_id)
        except ValueError:
            v_idx = 0
        color = VEHICLE_COLORS[v_idx % len(VEHICLE_COLORS)]

        # Build polyline coordinates: depot -> stop1 -> stop2 -> ...
        coords = []
        for stop in stops:
            coords.append([stop[6], stop[7]])  # lat, lon

        # Add depot at start if first stop isn't depot
        if depot_lat and coords and stops[0][8] is False:
            coords.insert(0, [depot_lat, depot_lon])

        # Add depot at end if last stop isn't depot
        if depot_lat and coords and stops[-1][8] is False:
            coords.append([depot_lat, depot_lon])

        if len(coords) >= 2:
            folium.PolyLine(
                locations=coords,
                color=color,
                weight=3,
                opacity=0.8,
                tooltip=f"{vehicle_id} ({scenario_tag})",
                popup=f"{vehicle_id} - {len(stops)} stops - Run: {run_id[:12]}",
            ).add_to(fg)

    # Add all scenario groups to map
    for fg in scenario_groups.values():
        fg.add_to(m)

    # Layer control (if multiple scenarios)
    if len(scenario_groups) > 1:
        folium.LayerControl(collapsed=False).add_to(m)

    return m


def main():
    print("=" * 60)
    print("HERMES - Route Map Generator")
    print("=" * 60)

    read_only = "motherduck_token" not in DB_PATH
    con = duckdb.connect(DB_PATH, read_only=read_only)

    rows = load_route_data(con)
    if not rows:
        print("  WARNING: No route solutions found. Skipping map generation.")
        con.close()
        sys.exit(0)

    vehicle_ids = load_vehicle_ids(con)
    con.close()

    print(f"  Route stops : {len(rows)}")
    print(f"  Vehicles    : {len(vehicle_ids)}")

    # Count scenarios
    scenarios = set(r[0] for r in rows)
    print(f"  Scenarios   : {', '.join(scenarios)}")

    m = build_map(rows, vehicle_ids)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_PATH)), exist_ok=True)

    m.save(OUTPUT_PATH)
    print(f"\n  Map saved to: {OUTPUT_PATH}")
    print("Done.")


if __name__ == "__main__":
    main()
