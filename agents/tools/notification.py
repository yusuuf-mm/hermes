"""
notification.py
---------------
Distribute operator alerts across available channels.

Tool: notification

This is a SCHEMA-ONLY skeleton. The stub writes nothing. Future work will:
  1. Wire this into agents/llm_client.py::complete() via the OpenAI
     `tools` parameter for function-calling.
  2. Implement at least one channel (console via Rich, DB row, webhook).
  3. Add rate limiting and dedup (avoid storming the dispatcher).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class NotificationLevel(str, Enum):
    """Severity of the operator alert."""
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"


class NotificationChannel(str, Enum):
    """Where the alert was delivered."""
    CONSOLE  = "console"
    DATABASE = "database"
    WEBHOOK  = "webhook"
    EMAIL    = "email"


class NotificationInput(BaseModel):
    """Input for the notification tool."""
    level:           NotificationLevel
    message:         str = Field(
        min_length=1, max_length=500,
        description="Operator-facing message.",
    )
    vehicle_id:      Optional[str] = Field(
        default=None,
        description="Affected vehicle_id (if applicable).",
    )
    node_id:         Optional[int] = Field(
        default=None,
        description="Affected node_id (if applicable).",
    )
    action_required: bool = Field(
        default=False,
        description="If true, mark the alert as needing human action.",
    )


class NotificationOutput(BaseModel):
    """Output of the notification tool."""
    delivered:       bool
    channels:        list[NotificationChannel]
    notification_id: str   = Field(description="Unique ID for dedup / audit trail.")
    emitted_at:      datetime


# ---------------------------------------------------------------------------
# Stub function — to be implemented in the tool-calling integration phase
# ---------------------------------------------------------------------------

def send_notification(input: NotificationInput) -> NotificationOutput:
    """
    Send an operator alert.

    CURRENTLY A STUB. Returns delivered=False with no channels. The real
    implementation will:
      - Generate a notification_id (uuid4().hex[:8]).
      - Print to console via Rich if level >= WARNING.
      - Insert a row into a 'notifications' table (if it exists).
      - Return delivered=True with the populated channel list.
    """
    return NotificationOutput(
        delivered=False,
        channels=[],
        notification_id="",
        emitted_at=datetime.utcnow(),
    )
