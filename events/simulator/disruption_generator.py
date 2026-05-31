"""
disruption_generator.py
-----------------------
Simulates real-world logistics disruptions throughout a delivery day.
Generates events at realistic frequencies, writes them to raw_events in DuckDB,
and prints a live feed so you can watch the system react.

Run standalone:
    python events/simulator/disruption_generator.py

Or import and call generate_batch() for testing.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from datetime import datetime

import duckdb

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from events.simulator.event_schemas import (
    EventType,
    FailedDeliveryEvent, FailedDeliveryPayload,
    LiveOrderEvent, LiveOrderPayload,
    RouteDeviationEvent, RouteDeviationPayload,
    TrafficDisruptionEvent, TrafficDisruptionPayload,
    VehicleBreakdownEvent, VehicleBreakdownPayload,
    VehicleTelemetryEvent, VehicleTelemetryPayload,
)

random.seed()   # non-deterministic for simulation realism

DB_PATH   = os.environ.get("HERMES_DB_PATH", "hermes.duckdb")
VEHICLE_IDS = [f"VH-{i:03d}" for i in range(1, 6)]

# Lagos metro bounding box for realistic coordinates
LAT_MIN, LAT_MAX = 6.42, 6.63
LON_MIN, LON_MAX = 3.22, 3.65


# ---------------------------------------------------------------------------
# Individual event generators
# ---------------------------------------------------------------------------

def gen_telemetry(vehicle_id: str | None = None) -> VehicleTelemetryEvent:
    vid = vehicle_id or random.choice(VEHICLE_IDS)
    return VehicleTelemetryEvent(
        vehicle_id=vid,
        payload=VehicleTelemetryPayload(
            lat=round(random.uniform(LAT_MIN, LAT_MAX), 6),
            lon=round(random.uniform(LON_MIN, LON_MAX), 6),
            speed_kmh=round(random.uniform(0, 55), 1),
            heading_deg=round(random.uniform(0, 359), 1),
            odometer_km=round(random.uniform(50, 350), 1),
            fuel_pct=round(random.uniform(15, 95), 1),
            engine_status=random.choice(["running", "running", "idle"]),
        ),
    )


def gen_route_deviation(vehicle_id: str | None = None) -> RouteDeviationEvent:
    vid = vehicle_id or random.choice(VEHICLE_IDS)
    return RouteDeviationEvent(
        vehicle_id=vid,
        node_id=random.randint(1, 25),
        payload=RouteDeviationPayload(
            planned_node_id=random.randint(1, 25),
            actual_lat=round(random.uniform(LAT_MIN, LAT_MAX), 6),
            actual_lon=round(random.uniform(LON_MIN, LON_MAX), 6),
            deviation_km=round(random.uniform(0.5, 8.0), 2),
            time_lost_min=round(random.uniform(5, 45), 1),
        ),
    )


def gen_traffic_disruption() -> TrafficDisruptionEvent:
    from_node = random.randint(0, 25)
    to_node   = random.randint(0, 25)
    while to_node == from_node:
        to_node = random.randint(0, 25)
    return TrafficDisruptionEvent(
        payload=TrafficDisruptionPayload(
            affected_from_node=from_node,
            affected_to_node=to_node,
            congestion_factor=round(random.uniform(1.3, 3.5), 2),
            duration_min=round(random.uniform(15, 120), 0),
            cause=random.choice(["accident", "roadwork", "flooding", "event"]),
        ),
    )


def gen_failed_delivery(vehicle_id: str | None = None) -> FailedDeliveryEvent:
    vid   = vehicle_id or random.choice(VEHICLE_IDS)
    nid   = random.randint(1, 25)
    oid   = f"ORD-{random.randint(1, 30):04d}"
    return FailedDeliveryEvent(
        vehicle_id=vid,
        node_id=nid,
        payload=FailedDeliveryPayload(
            node_id=nid,
            order_id=oid,
            reason=random.choice(["customer_absent", "address_error", "rejected"]),
            attempt_count=random.randint(1, 3),
            retry_window="15:00-17:00" if random.random() > 0.5 else None,
        ),
    )


def gen_live_order() -> LiveOrderEvent:
    nid = random.randint(1, 25)
    return LiveOrderEvent(
        node_id=nid,
        payload=LiveOrderPayload(
            order_id=f"ORD-LIVE-{random.randint(100, 999)}",
            node_id=nid,
            demand_units=random.randint(1, 20),
            priority=random.choice(["standard", "high", "critical"]),
            latest_delivery_time=random.randint(900, 1080),   # 15:00 – 18:00
        ),
    )


def gen_breakdown(vehicle_id: str | None = None) -> VehicleBreakdownEvent:
    vid = vehicle_id or random.choice(VEHICLE_IDS)
    return VehicleBreakdownEvent(
        vehicle_id=vid,
        payload=VehicleBreakdownPayload(
            lat=round(random.uniform(LAT_MIN, LAT_MAX), 6),
            lon=round(random.uniform(LON_MIN, LON_MAX), 6),
            breakdown_type=random.choice(["mechanical", "tyre", "accident", "fuel"]),
            estimated_repair_min=random.choice([30, 60, 90, None]),
            recovery_requested=random.random() > 0.5,
        ),
    )


# ---------------------------------------------------------------------------
# Event probability weights (per tick)
# Reflects realistic Lagos distribution of disruption types
# ---------------------------------------------------------------------------
EVENT_GENERATORS = [
    (gen_telemetry,          0.40),   # most frequent — GPS pings
    (gen_traffic_disruption, 0.25),   # Lagos traffic is notorious
    (gen_route_deviation,    0.15),
    (gen_failed_delivery,    0.12),
    (gen_live_order,         0.05),
    (gen_breakdown,          0.03),
]


def pick_event():
    gens, weights = zip(*EVENT_GENERATORS)
    return random.choices(gens, weights=weights, k=1)[0]()


# ---------------------------------------------------------------------------
# Database writer
# ---------------------------------------------------------------------------

def write_event(con: duckdb.DuckDBPyConnection, event) -> None:
    payload_dict = event.payload.model_dump()
    # Convert datetime objects to ISO strings for JSON serialisation
    for k, v in payload_dict.items():
        if isinstance(v, datetime):
            payload_dict[k] = v.isoformat()

    con.execute(
        """
        INSERT OR IGNORE INTO raw_events
            (event_id, event_type, vehicle_id, node_id, payload, emitted_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event.event_id,
            event.event_type.value,
            event.vehicle_id,
            event.node_id,
            json.dumps(payload_dict),
            event.emitted_at.isoformat(),
        ),
    )


# ---------------------------------------------------------------------------
# Batch generator (used by agents and tests)
# ---------------------------------------------------------------------------

def generate_batch(n: int = 20, db_path: str = DB_PATH) -> list:
    """Generate n random events, write to DB, return list of events."""
    con    = duckdb.connect(db_path)
    events = []
    for _ in range(n):
        evt = pick_event()
        write_event(con, evt)
        events.append(evt)
    con.close()
    return events


# ---------------------------------------------------------------------------
# Live simulation loop
# ---------------------------------------------------------------------------

SEVERITY_COLOUR = {
    EventType.VEHICLE_TELEMETRY:  "·",
    EventType.TRAFFIC_DISRUPTION: "⚠",
    EventType.ROUTE_DEVIATION:    "↗",
    EventType.FAILED_DELIVERY:    "✗",
    EventType.LIVE_ORDER:         "+",
    EventType.VEHICLE_BREAKDOWN:  "⛔",
}


def run_live(interval_s: float = 2.0, max_events: int | None = None):
    """
    Continuously generate events and write to DuckDB.
    Press Ctrl+C to stop.
    """
    con   = duckdb.connect(DB_PATH)
    count = 0

    print("HERMES Event Simulator — live mode")
    print(f"DB: {DB_PATH}  |  interval: {interval_s}s")
    print("-" * 60)

    try:
        while True:
            if max_events and count >= max_events:
                break

            evt    = pick_event()
            write_event(con, evt)
            symbol = SEVERITY_COLOUR.get(evt.event_type, "?")
            vid    = evt.vehicle_id or "---"
            print(
                f"[{datetime.utcnow().strftime('%H:%M:%S')}] "
                f"{symbol} {evt.event_type.value:<22} "
                f"vehicle={vid:<8} id={evt.event_id}"
            )
            count += 1
            time.sleep(interval_s)

    except KeyboardInterrupt:
        print(f"\nStopped after {count} events.")
    finally:
        con.close()


if __name__ == "__main__":
    run_live(interval_s=1.5)
