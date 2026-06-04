"""
event_schemas.py
----------------
Pydantic models for all HERMES event types.
These are the canonical shapes written to raw_events.payload (JSON).
Agents deserialise from these models — never from raw dicts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Event type registry
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    VEHICLE_TELEMETRY  = "vehicle_telemetry"
    ROUTE_DEVIATION    = "route_deviation"
    TRAFFIC_DISRUPTION = "traffic_disruption"
    FAILED_DELIVERY    = "failed_delivery"
    LIVE_ORDER         = "live_order"
    VEHICLE_BREAKDOWN  = "vehicle_breakdown"


class EventSeverity(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Base event envelope
# ---------------------------------------------------------------------------

class BaseEvent(BaseModel):
    event_id:   str       = Field(default_factory=lambda: f"EVT-{uuid.uuid4().hex[:8].upper()}")
    event_type: EventType
    vehicle_id: Optional[str] = None
    node_id:    Optional[int] = None
    emitted_at: datetime  = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Concrete event payloads
# ---------------------------------------------------------------------------

class VehicleTelemetryPayload(BaseModel):
    lat:          float
    lon:          float
    speed_kmh:    float
    heading_deg:  float
    odometer_km:  float
    fuel_pct:     float
    engine_status: str   # "running" | "idle" | "off"


class RouteDeviationPayload(BaseModel):
    planned_node_id:  int
    actual_lat:       float
    actual_lon:       float
    deviation_km:     float   # distance from planned route
    time_lost_min:    float


class TrafficDisruptionPayload(BaseModel):
    affected_from_node: int
    affected_to_node:   int
    congestion_factor:  float   # multiplier: 1.0 = normal, 2.0 = 2× slower
    duration_min:       float
    cause:              str     # "accident" | "roadwork" | "flooding" | "event"


class FailedDeliveryPayload(BaseModel):
    node_id:       int
    order_id:      str
    reason:        str   # "customer_absent" | "address_error" | "rejected"
    attempt_count: int
    retry_window:  Optional[str] = None   # e.g. "14:00-16:00"


class LiveOrderPayload(BaseModel):
    order_id:      str
    node_id:       int
    demand_units:  int
    priority:      str   # "standard" | "high" | "critical"
    latest_delivery_time: int   # minutes from midnight


class VehicleBreakdownPayload(BaseModel):
    lat:           float
    lon:           float
    breakdown_type: str    # "mechanical" | "tyre" | "accident" | "fuel"
    estimated_repair_min: Optional[int] = None
    recovery_requested:   bool = False


# ---------------------------------------------------------------------------
# Typed event wrappers (what actually goes into raw_events)
# ---------------------------------------------------------------------------

class VehicleTelemetryEvent(BaseEvent):
    event_type: EventType = EventType.VEHICLE_TELEMETRY
    payload: VehicleTelemetryPayload

class RouteDeviationEvent(BaseEvent):
    event_type: EventType = EventType.ROUTE_DEVIATION
    payload: RouteDeviationPayload

class TrafficDisruptionEvent(BaseEvent):
    event_type: EventType = EventType.TRAFFIC_DISRUPTION
    payload: TrafficDisruptionPayload

class FailedDeliveryEvent(BaseEvent):
    event_type: EventType = EventType.FAILED_DELIVERY
    payload: FailedDeliveryPayload

class LiveOrderEvent(BaseEvent):
    event_type: EventType = EventType.LIVE_ORDER
    payload: LiveOrderPayload

class VehicleBreakdownEvent(BaseEvent):
    event_type: EventType = EventType.VEHICLE_BREAKDOWN
    payload: VehicleBreakdownPayload
