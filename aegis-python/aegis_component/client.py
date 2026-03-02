"""
AegisComponent — async client library for Aegis components.

Usage:
    from aegis_component import AegisComponent, ComponentConfig

    class MyComponent(AegisComponent):
        async def on_configure(self, socket_path, topics):
            ...
        async def on_running(self):
            ...
        async def on_shutdown(self):
            ...

    asyncio.run(MyComponent(ComponentConfig(...)).run())
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from .log import get_logger
from .protocol import (
    Command,
    ComponentState,
    MessageType,
    new_envelope,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ComponentConfig:
    socket_path:          str
    session_token:        str
    component_name:       str
    version:              str       = "0.1.0"
    supported_symbols:    list[str] = field(default_factory=list)
    supported_timeframes: list[str] = field(default_factory=list)
    requires_streams:     list[str] = field(default_factory=list)

    # Reconnection
    reconnect:            bool  = True
    reconnect_delay:      float = 3.0   # seconds between attempts
    max_reconnect_delay:  float = 60.0  # cap for exponential backoff
    max_reconnect_attempts: int = 0     # 0 = unlimited

    # Logging
    log_level: int = logging.INFO


# ---------------------------------------------------------------------------
# AegisComponent
# ---------------------------------------------------------------------------

class AegisComponent:
    """
    Base class for all Aegis components.

    Subclass and override the async on_* hooks to implement your logic.
    All protocol communication (registration, heartbeat, state transitions,
    reconnection) is handled automatically.
    """

    def __init__(self, config: ComponentConfig) -> None:
        self.config       = config
        self.component_id: Optional[str] = None
        self.session_id:   Optional[str] = None
        self.state        = ComponentState.INIT
        self._started_at  = asyncio.get_event_loop().time()

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._running     = False
        self._send_lock   = asyncio.Lock()

        self.log = get_logger(
            f"aegis.{config.component_name}",
            config.log_level,
        )

        # Callbacks — can also be set directly:
        #   component.on_ping = my_async_fn
        self.on_ping:      Optional[Callable[[], Awaitable[None]]] = None
        self.on_configure: Optional[Callable[[str, list[str]], Awaitable[None]]] = None
        self.on_running:   Optional[Callable[[], Awaitable[None]]] = None
        self.on_shutdown:  Optional[Callable[[], Awaitable[None]]] = None
        self.on_error:     Optional[Callable[[str, str], Awaitable[None]]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """
        Connect, register, and enter the message loop.
        Handles reconnection automatically if config.reconnect is True.
        """
        attempts  = 0
        delay     = self.config.reconnect_delay

        while True:
            try:
                await self._connect()
                await self._register()
                self._running = True
                delay = self.config.reconnect_delay  # reset on success
                await self._message_loop()
            except (ConnectionRefusedError, FileNotFoundError, OSError) as exc:
                self.log.warning("Connection error: %s", exc)
            except RegistrationError as exc:
                self.log.error("Registration failed (will not retry): %s", exc)
                break
            finally:
                await self._close_connection()

            if not self.config.reconnect:
                break

            attempts += 1
            if self.config.max_reconnect_attempts and attempts >= self.config.max_reconnect_attempts:
                self.log.error("Max reconnect attempts reached (%d), giving up", attempts)
                break

            self.log.info("Reconnecting in %.1fs (attempt %d)...", delay, attempts)
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.config.max_reconnect_delay)

    async def send_state_update(
        self,
        new_state: ComponentState,
        message: Optional[str] = None,
        uptime_seconds: Optional[int] = None,
    ) -> None:
        """Explicitly send a STATE_UPDATE to Aegis."""
        payload: dict[str, Any] = {"state": new_state.value}
        if message:
            payload["message"] = message
        if uptime_seconds is not None:
            payload["uptime_seconds"] = uptime_seconds
        await self._send(new_envelope(MessageType.LIFECYCLE, Command.STATE_UPDATE, self._source, payload))
        self.state = new_state

    async def send_error(self, code: str, message: str, recoverable: bool = True) -> None:
        """Report a runtime error to Aegis."""
        await self._send(new_envelope(
            MessageType.ERROR,
            Command.RUNTIME_ERROR,
            self._source,
            {"code": code, "message": message, "recoverable": recoverable},
        ))

    # ------------------------------------------------------------------
    # Hooks — override in subclasses OR assign callables
    # ------------------------------------------------------------------

    async def _invoke_on_ping(self) -> None:
        if self.on_ping:
            await self.on_ping()

    async def _invoke_on_configure(self, socket_path: str, topics: list[str]) -> None:
        if self.on_configure:
            await self.on_configure(socket_path, topics)

    async def _invoke_on_running(self) -> None:
        if self.on_running:
            await self.on_running()

    async def _invoke_on_shutdown(self) -> None:
        if self.on_shutdown:
            await self.on_shutdown()

    async def _invoke_on_error(self, code: str, message: str) -> None:
        if self.on_error:
            await self.on_error(code, message)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @property
    def _source(self) -> str:
        return f"component:{self.config.component_name}"

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

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def _register(self) -> None:
        envelope = new_envelope(
            MessageType.LIFECYCLE,
            Command.REGISTER,
            self._source,
            {
                "session_token":  self.config.session_token,
                "component_name": self.config.component_name,
                "version":        self.config.version,
                "capabilities": {
                    "supported_symbols":    self.config.supported_symbols,
                    "supported_timeframes": self.config.supported_timeframes,
                    "requires_streams":     self.config.requires_streams,
                },
            },
        )
        await self._send(envelope)

        response = await self._recv()
        if response.get("command") != Command.REGISTERED.value:
            raise RegistrationError(f"Unexpected response: {response}")

        payload           = response["payload"]
        self.component_id = payload["component_id"]
        self.session_id   = payload["session_id"]
        self.state        = ComponentState.REGISTERED

        self.log.info(
            "Registered — component_id=%s session_id=%s",
            self.component_id,
            self.session_id,
        )

    # ------------------------------------------------------------------
    # Message loop
    # ------------------------------------------------------------------

    async def _message_loop(self) -> None:
        self.log.debug("Entering message loop")

        while self._running:
            try:
                envelope = await asyncio.wait_for(self._recv(), timeout=35.0)
            except asyncio.TimeoutError:
                self.log.warning("Read timeout — connection may be dead")
                break
            except (OSError, asyncio.IncompleteReadError):
                self.log.warning("Connection closed by Aegis")
                break

            msg_type = envelope.get("type")
            command  = envelope.get("command")
            self.log.debug("Received type=%s command=%s", msg_type, command)

            if msg_type == MessageType.HEARTBEAT.value:
                await self._handle_heartbeat(envelope)
            elif msg_type == MessageType.CONFIG.value:
                await self._handle_config(envelope)
            elif msg_type == MessageType.LIFECYCLE.value:
                await self._handle_lifecycle(envelope)
            elif msg_type == MessageType.ERROR.value:
                await self._handle_error_msg(envelope)
            else:
                self.log.warning("Unknown message type: %s", msg_type)

        await self._graceful_shutdown()

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_heartbeat(self, envelope: dict) -> None:
        if envelope["command"] == Command.PING.value:
            await self._invoke_on_ping()
            uptime = int(asyncio.get_event_loop().time() - self._started_at)
            pong = new_envelope(
                MessageType.HEARTBEAT,
                Command.PONG,
                self._source,
                {"state": self.state.value, "uptime_seconds": uptime},
                correlation_id=envelope["message_id"],
            )
            await self._send(pong)
            self.log.debug("Sent PONG (uptime=%ds)", uptime)

    async def _handle_config(self, envelope: dict) -> None:
        if envelope["command"] != Command.CONFIGURE.value:
            return

        payload     = envelope["payload"]
        sock_path   = payload.get("data_stream_socket", "")
        topics      = payload.get("topics", [])

        self.log.info("Configuring — socket=%s topics=%s", sock_path, topics)

        await self._invoke_on_configure(sock_path, topics)
        await self._send_ack(envelope["message_id"])

        await self.send_state_update(ComponentState.CONFIGURED)
        await self.send_state_update(ComponentState.RUNNING)

        self.log.info("Component is now RUNNING")
        await self._invoke_on_running()

    async def _handle_lifecycle(self, envelope: dict) -> None:
        command = envelope.get("command")

        if command == Command.SHUTDOWN.value:
            self.log.info("Shutdown requested by Aegis")
            await self._send_ack(envelope["message_id"])
            self._running = False

        elif command == Command.ACK.value:
            self.log.debug("ACK received")

        else:
            self.log.warning("Unknown lifecycle command: %s", command)

    async def _handle_error_msg(self, envelope: dict) -> None:
        payload = envelope.get("payload", {})
        code    = payload.get("code", "UNKNOWN")
        message = payload.get("message", "")

        self.log.error("Error from Aegis — code=%s message=%s", code, message)
        await self._invoke_on_error(code, message)

        if not payload.get("recoverable", False):
            self._running = False

    # ------------------------------------------------------------------
    # Graceful shutdown
    # ------------------------------------------------------------------

    async def _graceful_shutdown(self) -> None:
        self.log.info("Shutting down...")
        await self._invoke_on_shutdown()

        try:
            shutdown_env = new_envelope(
                MessageType.LIFECYCLE,
                Command.SHUTDOWN,
                self._source,
                {},
            )
            await self._send(shutdown_env)
        except OSError:
            pass

        self.state = ComponentState.SHUTDOWN
        self.log.info("Shutdown complete")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _send_ack(self, correlation_id: str) -> None:
        ack = new_envelope(
            MessageType.CONTROL,
            Command.ACK,
            self._source,
            {"status": "ok"},
            correlation_id=correlation_id,
        )
        await self._send(ack)

    async def _send(self, envelope: dict[str, Any]) -> None:
        async with self._send_lock:
            data = json.dumps(envelope) + "\n"
            self._writer.write(data.encode())
            await self._writer.drain()

    async def _recv(self) -> dict[str, Any]:
        line = await self._reader.readline()
        if not line:
            raise OSError("Connection closed")
        return json.loads(line)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RegistrationError(Exception):
    pass
