"""
schemas.py
----------
Pydantic v2 response schemas for every HERMES agent node.

Each agent receives a free-form LLM response and must convert it into a
typed, validated structure before writing back to HermesState. These
models replace the previous `json.loads() + try/except` pattern with
explicit shape, range, and enum validation.

Usage in an agent:
    from agents.schemas import MonitoringOutput

    raw = complete(...)
    try:
        result = MonitoringOutput.model_validate_json(raw)
    except ValidationError:
        result = MonitoringOutput(...)  # safe fallback

Conventions:
- 0.0–1.0 probability fields use `confloat(ge=0.0, le=1.0)`.
- Closed enums use `str, Enum` so the JSON value round-trips cleanly and
  `instance == "low"` comparisons still work in normal Python code.
- Optional confidence fields default to None — the LLM is not required
  to emit them, but is validated if it does.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, RootModel, confloat

# ---------------------------------------------------------------------------
# Closed enums — str subclasses so JSON values and Python str compare equal
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class Category(str, Enum):
    OPERATIONAL = "operational"
    SAFETY      = "safety"
    SLA_RISK    = "sla_risk"
    CAPACITY    = "capacity"
    NEW_DEMAND  = "new_demand"


class RiskLevel(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class Urgency(str, Enum):
    IMMEDIATE     = "immediate"
    WITHIN_30_MIN = "within_30_min"
    MONITOR_ONLY  = "monitor_only"


class Strategy(str, Enum):
    FULL_REPLAN    = "full_replan"
    PARTIAL_REPLAN = "partial_replan"
    VEHICLE_SWAP   = "vehicle_swap"
    HOLD           = "hold"


class ConstraintsToRelax(str, Enum):
    TIME_WINDOWS = "time_windows"
    CAPACITY     = "capacity"
    BOTH         = "both"
    NONE         = "none"


Score01 = confloat(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Monitoring Agent (Agent 1)
# ---------------------------------------------------------------------------

class MonitoringOutput(BaseModel):
    anomalies_detected:   bool
    anomaly_count:        int  = Field(ge=0)
    anomaly_types:        list[str]
    monitoring_summary:   str
    confidence_score:     Optional[Score01] = None


# ---------------------------------------------------------------------------
# Classification Agent (Agent 2)
# ---------------------------------------------------------------------------

class ClassifiedEvent(BaseModel):
    event_id:            str
    event_type:          str
    severity:            Severity
    category:            Category
    operational_impact:  str
    confidence_score:    Optional[Score01] = None


class ClassificationOutput(RootModel[list[ClassifiedEvent]]):
    """The LLM returns a JSON array; RootModel unwraps to `list[ClassifiedEvent]`."""


# ---------------------------------------------------------------------------
# SLA Risk Agent (Agent 3)
# ---------------------------------------------------------------------------

class SLARiskReport(BaseModel):
    overall_risk_level: RiskLevel
    sla_risk_score:     Score01
    at_risk_nodes:      list[int]
    at_risk_vehicles:   list[str]
    risk_factors:       list[str]
    reasoning:          str
    confidence_score:   Optional[Score01] = None


# ---------------------------------------------------------------------------
# Rerouting Agent (Agent 4)
# ---------------------------------------------------------------------------

class ReroutingDecision(BaseModel):
    should_resolve:          bool
    urgency:                 Urgency
    affected_vehicles:       list[str]
    strategy:                Strategy
    constraints_to_relax:    ConstraintsToRelax
    reason:                  str
    human_approval_required: bool
    confidence_score:        Optional[Score01] = None


# ---------------------------------------------------------------------------
# Dispatch Agent (Agent 5)
# ---------------------------------------------------------------------------

class DispatchOutput(BaseModel):
    """Dispatch returns a free-form text brief. We validate it parses and is
    non-empty; structural sections are not strictly enforced to keep the
    LLM flexible, but length must be sane."""
    brief: str = Field(min_length=1, max_length=4000)
