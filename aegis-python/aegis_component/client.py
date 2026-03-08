"""
AegisComponent — async client library for Aegis components.

Full lifecycle:
  connect → REGISTER → recv REGISTERED
  → send STATE_UPDATE(INITIALIZING) → recv ACK
  → send STATE_UPDATE(READY)
  → recv CONFIGURE → send ACK → send STATE_UPDATE(CONFIGURED)
  → invoke on_configure(socket_path, topics)
  → send STATE_UPDATE(RUNNING) → invoke on_running()
  → message loop (PING/PONG heartbeats, SHUTDOWN, ERROR)
  → graceful shutdown → send SHUTDOWN → invoke on_shutdown()

Environment variables (injected automatically by Aegis when launched via attach):
  AEGIS_SESSION_TOKEN    — session ID for the REGISTER handshake
  AEGIS_COMPONENT_SOCKET — Unix socket path to connect to the daemon

Usage:
    from aegis_component import AegisComponent, ComponentConfig

    class MyComponent(AegisComponent):
        async def on_configure(self, socket_path, topics):
            ...
        async def on_running(self):
            ...
        async def on_shutdown(self):
            ...

    asyncio.run(MyComponent(ComponentConfig.from_env(
        component_name       = "my_component",
        supported_symbols    = ["BTCUSDT"],
        supported_timeframes = ["1m"],
        requires_streams     = ["klines"],
    )).run())
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

PROTOCOL_VERSION = "0.1.0"


class MessageType(str, Enum):
    CONTROL   = "CONTROL"
    LIFECYCLE = "LIFECYCLE"
    CONFIG    = "CONFIG"
    ERROR     = "ERROR"
    HEARTBEAT = "HEARTBEAT"
    DATA      = "DATA"


class Command(str, Enum):
    REGISTER            = "REGISTER"
    REGISTERED          = "REGISTERED"
    STATE_UPDATE        = "STATE_UPDATE"
    SHUTDOWN            = "SHUTDOWN"
    ACK                 = "ACK"
    NACK                = "NACK"
    CONFIGURE           = "CONFIGURE"
    CONFIGURED          = "CONFIGURED"
    PING                = "PING"
    PONG                = "PONG"
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
    msg_type, command, source, payload,
    correlation_id=None,
    target="aegis",
) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "message_id":       str(uuid.uuid4()),
        "correlation_id":   correlation_id,
        "timestamp":        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source":           source,
        "target":           target,
        "type":             msg_type.value,
        "command":          command.value,
        "payload":          payload,
    }


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ComponentConfig:
    socket_path:            str        # Unix socket to the Aegis daemon
    session_token:          str        # AEGIS_SESSION_TOKEN
    component_name:         str
    component_id:           str        = ""
    version:                str        = "0.1.0"
    supported_symbols:      list[str]  = field(default_factory=list)
    supported_timeframes:   list[str]  = field(default_factory=list)
    requires_streams:       list[str]  = field(default_factory=list)

    # Reconnection
    reconnect:              bool  = True
    reconnect_delay:        float = 3.0
    max_reconnect_delay:    float = 60.0
    max_reconnect_attempts: int   = 0      # 0 = unlimited

    # Timeouts
    read_timeout: float = 35.0

    # Logging
    log_level: int = logging.INFO

    @classmethod
    def from_env(
        cls,
        component_name:       str,
        version:              str       = "0.1.0",
        supported_symbols:    list[str] = None,
        supported_timeframes: list[str] = None,
        requires_streams:     list[str] = None,
        component_id: str = "",
        **kwargs,
    ) -> "ComponentConfig":
        """
        Build a ComponentConfig from Aegis-injected environment variables.

        AEGIS_SESSION_TOKEN    — required, injected by `aegis session attach`
        AEGIS_COMPONENT_SOCKET — required, injected by `aegis session attach`

        Any extra keyword arguments are forwarded to the constructor
        (e.g. reconnect_delay, log_level).
        """
        session_token = os.environ.get("AEGIS_SESSION_TOKEN")
        socket_path   = os.environ.get("AEGIS_COMPONENT_SOCKET")
        component_id  = os.environ.get("AEGIS_COMPONENT_ID", "") 


        if not session_token:
            raise EnvironmentError(
                "AEGIS_SESSION_TOKEN is not set. "
                "Make sure the component is launched via 'aegis session attach'."
            )
        if not socket_path:
            raise EnvironmentError(
                "AEGIS_COMPONENT_SOCKET is not set. "
                "Make sure the component is launched via 'aegis session attach'."
            )

        return cls(
            socket_path           = socket_path,
            session_token         = session_token,
            component_name        = component_name,
            version               = version,
            supported_symbols     = supported_symbols    or [],
            supported_timeframes  = supported_timeframes or [],
            requires_streams      = requires_streams     or [],
            component_id          = component_id,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# AegisComponent
# ---------------------------------------------------------------------------

class AegisComponent:
    """
    Base class for all Aegis components.

    Subclass and override the async on_* hooks to implement your logic.
    All protocol communication (registration, heartbeat, state transitions,
    reconnection) is handled automatically.

    Recommended usage — let Aegis inject the config from the environment:

        class MyComponent(AegisComponent):
            async def on_configure(self, socket_path, topics): ...
            async def on_running(self): ...
            async def on_shutdown(self): ...

        asyncio.run(MyComponent(ComponentConfig.from_env(
            component_name       = "my_component",
            supported_symbols    = ["BTCUSDT"],
            supported_timeframes = ["1m"],
            requires_streams     = ["klines"],
        )).run())
    """

    def __init__(self, config: ComponentConfig) -> None:
        self.config       = config
        self.component_id: Optional[str] = None
        self.session_id:   Optional[str] = None
        self.state        = ComponentState.INIT
        self._started_at  = time.monotonic()

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._running    = False
        self._send_lock  = asyncio.Lock()

        self.log = logging.getLogger(f"aegis.{config.component_name}")
        if not self.log.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
            ))
            self.log.addHandler(handler)
        self.log.setLevel(config.log_level)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """
        Connect, register, signal READY, and enter the message loop.
        Handles reconnection automatically if config.reconnect is True.
        """
        attempts = 0
        delay    = self.config.reconnect_delay

        while True:
            try:
                await self._connect()
                await self._register()
                await self._signal_ready()
                self._running = True
                delay = self.config.reconnect_delay  # reset backoff on success
                await self._message_loop()
            except (ConnectionRefusedError, FileNotFoundError, OSError) as exc:
                self.log.warning("Connection error: %s", exc)
            except RegistrationError as exc:
                self.log.error("Registration failed (will not retry): %s", exc)
                break
            finally:
                self._running = False
                await self._close_connection()

            if not self.config.reconnect:
                break

            attempts += 1
            if self.config.max_reconnect_attempts and attempts >= self.config.max_reconnect_attempts:
                self.log.error("Max reconnect attempts reached (%d), giving up", attempts)
                break

            self.log.info("Reconnecting in %.1fs (attempt %d)…", delay, attempts)
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.config.max_reconnect_delay)

    async def send_state_update(
        self,
        new_state: ComponentState,
        message: Optional[str] = None,
        uptime_seconds: Optional[int] = None,
    ) -> None:
        """Explicitly send a STATE_UPDATE to Aegis and update local state."""
        payload: dict[str, Any] = {"state": new_state.value}
        if message:
            payload["message"] = message
        if uptime_seconds is not None:
            payload["uptime_seconds"] = uptime_seconds

        await self._send(
            new_envelope(MessageType.LIFECYCLE, Command.STATE_UPDATE, self._source, payload)
        )
        self.state = new_state
        self.log.debug("State → %s", new_state.value)

    async def send_error(self, code: str, message: str, recoverable: bool = True) -> None:
        """Report a runtime error to Aegis."""
        await self._send(new_envelope(
            MessageType.ERROR,
            Command.RUNTIME_ERROR,
            self._source,
            {"code": code, "message": message, "recoverable": recoverable},
        ))

    # ------------------------------------------------------------------
    # Hooks — override in subclasses
    # ------------------------------------------------------------------

    async def on_configure(self, socket_path: str, topics: list[str]) -> None:
        """
        Called after CONFIGURE is received and ACKed.
        Use this to connect to the data stream socket and subscribe to topics.
        socket_path is the per-session Unix socket where market data flows.
        """

    async def on_running(self) -> None:
        """Called after STATE_UPDATE(RUNNING) is sent. Start your business logic here."""

    async def on_shutdown(self) -> None:
        """Called during graceful shutdown. Release resources here."""

    async def on_ping(self) -> None:
        """Called on every PING received. Override to add custom heartbeat logic."""

    async def on_error(self, code: str, message: str) -> None:
        """Called when Aegis sends an ERROR message."""

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @property
    def _source(self) -> str:
        return f"component:{self.config.component_name}"

    @property
    def _uptime_seconds(self) -> int:
        return int(time.monotonic() - self._started_at)

    async def _connect(self) -> None:
        self.log.info("Connecting to %s", self.config.socket_path)
        self._reader, self._writer = await asyncio.open_unix_connection(
            self.config.socket_path
        )
        self.log.info("Connected")

    async def _close_connection(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except OSError:
                pass
            self._writer = None
            self._reader = None

    async def _register(self) -> None:
        payload = {
            "session_token":  self.config.session_token,
            "component_name": self.config.component_name,
            "version":        self.config.version,
            "capabilities": {
                "supported_symbols":    self.config.supported_symbols,
                "supported_timeframes": self.config.supported_timeframes,
                "requires_streams":     self.config.requires_streams,
            },
        }
        if self.config.component_id:
            payload["component_id"] = self.config.component_id

        envelope = new_envelope(  # ← asignar a variable
            MessageType.LIFECYCLE,
            Command.REGISTER,
            self._source,
            payload,
        )

        await self._send(envelope)
        self.log.debug("REGISTER sent, waiting for REGISTERED response...")

        response = await self._recv()

        if response.get("type") == MessageType.ERROR.value:
            payload = response.get("payload", {})
            raise RegistrationError(
                f"Server rejected registration: {payload.get('reason', payload)}"
            )

        if response.get("command") != Command.REGISTERED.value:
            raise RegistrationError(f"Unexpected response to REGISTER: {response}")

        payload           = response["payload"]
        self.component_id = payload["component_id"]
        self.session_id   = payload["session_id"]
        self.state        = ComponentState.REGISTERED

        self.log.info(
            "Registered — component_id=%s  session_id=%s",
            self.component_id,
            self.session_id,
        )

    async def _signal_ready(self) -> None:
        await self.send_state_update(ComponentState.INITIALIZING)
        ack = await self._recv()
        self.log.debug("ACK for INITIALIZING: %s", ack.get("command"))
        await self.send_state_update(ComponentState.READY)
        self.log.info("Signalled READY — waiting for CONFIGURE")

    async def _message_loop(self) -> None:
        while self._running:
            try:
                envelope = await asyncio.wait_for(
                    self._recv(), timeout=self.config.read_timeout
                )
            except asyncio.TimeoutError:
                self.log.warning("Read timeout — connection may be dead")
                break
            except (OSError, asyncio.IncompleteReadError):
                self.log.warning("Connection closed by Aegis")
                break

            msg_type = envelope.get("type")
            command  = envelope.get("command")
            self.log.debug("Received  type=%-12s  command=%s", msg_type, command)

            if msg_type == MessageType.HEARTBEAT.value:
                await self._handle_heartbeat(envelope)
            elif msg_type == MessageType.CONFIG.value:
                await self._handle_config(envelope)
            elif msg_type == MessageType.LIFECYCLE.value:
                await self._handle_lifecycle(envelope)
            elif msg_type == MessageType.CONTROL.value:
                await self._handle_control(envelope)
            elif msg_type == MessageType.ERROR.value:
                await self._handle_error_msg(envelope)
            else:
                self.log.warning("Unknown message type: %s", msg_type)

        await self._graceful_shutdown()

    async def _handle_heartbeat(self, envelope: dict) -> None:
        if envelope["command"] != Command.PING.value:
            return
        await self.on_ping()
        pong = new_envelope(
            MessageType.HEARTBEAT,
            Command.PONG,
            self._source,
            {"state": self.state.value, "uptime_seconds": self._uptime_seconds},
            correlation_id=envelope["message_id"],
        )
        await self._send(pong)
        self.log.debug("Sent PONG (uptime=%ds)", self._uptime_seconds)

    async def _handle_control(self, envelope: dict) -> None:
        command = envelope.get("command")
        if command == Command.ACK.value:
            self.log.debug("ACKed (correlation_id=%s)", envelope.get("correlation_id"))
        elif command == Command.NACK.value:
            payload = envelope.get("payload", {})
            self.log.error("NACKed — reason=%s", payload.get("message", "unknown"))
            self._running = False
        else:
            self.log.warning("Unknown CONTROL command: %s", command)

    async def _handle_config(self, envelope: dict) -> None:
        if envelope["command"] != Command.CONFIGURE.value:
            self.log.warning("Unknown CONFIG command: %s", envelope.get("command"))
            return

        payload   = envelope.get("payload", {})
        sock_path = payload.get("data_stream_socket", "")
        topics    = payload.get("topics", [])

        self.log.info("Received CONFIGURE — socket=%s  topics=%s", sock_path, topics)

        await self._send_ack(envelope["message_id"])
        await self.send_state_update(ComponentState.CONFIGURED)
        await self.on_configure(sock_path, topics)
        await self.send_state_update(ComponentState.RUNNING)
        self.log.info("Component is now RUNNING")
        await self.on_running()

    async def _handle_lifecycle(self, envelope: dict) -> None:
        command = envelope.get("command")
        if command == Command.SHUTDOWN.value:
            self.log.info("Shutdown requested by Aegis")
            await self._send_ack(envelope["message_id"])
            self._running = False
        elif command == Command.ACK.value:
            self.log.debug("ACK received for correlation_id=%s", envelope.get("correlation_id"))
        else:
            self.log.warning("Unknown lifecycle command: %s", command)

    async def _handle_error_msg(self, envelope: dict) -> None:
        payload = envelope.get("payload", {})
        code    = payload.get("code", "UNKNOWN")
        message = payload.get("message", "")
        self.log.error("Error from Aegis — code=%s  message=%s", code, message)
        await self.on_error(code, message)
        if not payload.get("recoverable", False):
            self.log.error("Non-recoverable error — stopping")
            self._running = False

    async def _graceful_shutdown(self) -> None:
        self.log.info("Initiating graceful shutdown…")
        try:
            await self._send(new_envelope(
                MessageType.LIFECYCLE, Command.SHUTDOWN, self._source, {}
            ))
            self.log.debug("Sent SHUTDOWN")
        except OSError:
            pass
        await self.on_shutdown()
        self.state = ComponentState.SHUTDOWN
        self.log.info("Shutdown complete")

    async def _send_ack(self, correlation_id: str) -> None:
        ack = new_envelope(
            MessageType.CONTROL,
            Command.ACK,
            self._source,
            {"status": "ok"},
            correlation_id=correlation_id,
        )
        await self._send(ack)
        self.log.debug("Sent ACK (correlation_id=%s)", correlation_id)

    async def _send(self, envelope: dict[str, Any]) -> None:
        async with self._send_lock:
            data = json.dumps(envelope) + "\n"
            self._writer.write(data.encode())
            await self._writer.drain()

    async def _recv(self) -> dict[str, Any]:
        assert self._reader is not None, "Not connected"
        line = await self._reader.readline()
        if not line:
            raise OSError("Connection closed")
        return json.loads(line)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RegistrationError(Exception):
    pass