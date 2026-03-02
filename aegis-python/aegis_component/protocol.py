"""
Protocol types and envelope helpers for the Aegis component protocol.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Optional


PROTOCOL_VERSION = "0.1"


class MessageType(str, Enum):
    CONTROL   = "CONTROL"
    LIFECYCLE = "LIFECYCLE"
    CONFIG    = "CONFIG"
    ERROR     = "ERROR"
    HEARTBEAT = "HEARTBEAT"
    DATA      = "DATA"


class Command(str, Enum):
    REGISTER    = "REGISTER"
    REGISTERED  = "REGISTERED"
    STATE_UPDATE = "STATE_UPDATE"
    SHUTDOWN    = "SHUTDOWN"
    ACK         = "ACK"
    NACK        = "NACK"
    CONFIGURE   = "CONFIGURE"
    CONFIGURED  = "CONFIGURED"
    PING        = "PING"
    PONG        = "PONG"
    RUNTIME_ERROR       = "RUNTIME_ERROR"
    REGISTRATION_FAILED = "REGISTRATION_FAILED"


class ComponentState(str, Enum):
    INIT         = "INIT"
    REGISTERED   = "REGISTERED"
    INITIALIZING = "INITIALIZING"
    READY        = "READY"
    CONFIGURED   = "CONFIGURED"
    RUNNING      = "RUNNING"
    WAITING      = "WAITING"
    ERROR        = "ERROR"
    FINISHED     = "FINISHED"
    SHUTDOWN     = "SHUTDOWN"


def new_envelope(
    msg_type: MessageType,
    command: Command,
    source: str,
    payload: dict[str, Any],
    correlation_id: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "message_id":       str(uuid.uuid4()),
        "correlation_id":   correlation_id,
        "timestamp":        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source":           source,
        "target":           "aegis",
        "type":             msg_type.value,
        "command":          command.value,
        "payload":          payload,
    }
