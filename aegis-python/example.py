"""
Example: MarketDataComponent
============================
A simple component that simulates consuming market data once configured.

Run with:
    python example.py
"""

import asyncio
import logging

from aegis_component import AegisComponent, ComponentConfig, ComponentState


class MarketDataComponent(AegisComponent):
    """
    Example component that simulates reading market data from a stream.
    """

    def __init__(self, config: ComponentConfig) -> None:
        super().__init__(config)
        self._stream_socket: str      = ""
        self._topics:        list[str] = []
        self._worker_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    async def on_configure(self, socket_path: str, topics: list[str]) -> None:
        """Store the stream configuration."""
        self._stream_socket = socket_path
        self._topics        = topics
        self.log.info("Configuration received — socket=%s topics=%s", socket_path, topics)

        # In a real component you'd connect to the data stream here:
        # reader, writer = await asyncio.open_unix_connection(socket_path)

    async def on_running(self) -> None:
        """Start the data processing worker."""
        self._worker_task = asyncio.create_task(self._data_worker())

    async def on_shutdown(self) -> None:
        """Cancel the worker and clean up."""
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self.log.info("Resources released")

    # ------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------

    async def _data_worker(self) -> None:
        """Simulates processing data ticks."""
        tick = 0
        while True:
            tick += 1
            self.log.info(
                "Tick #%d — processing symbols=%s (state=%s)",
                tick,
                self._topics,
                self.state.value,
            )

            # Simulate transitioning to WAITING between ticks
            await self.send_state_update(ComponentState.WAITING)
            await asyncio.sleep(2)
            await self.send_state_update(ComponentState.RUNNING)
            await asyncio.sleep(3)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    config = ComponentConfig(
        socket_path           = "/tmp/aegis_components.sock",
        session_token         = "YOUR_SESSION_TOKEN_HERE",
        component_name        = "market_data",
        version               = "0.1.0",
        supported_symbols     = ["BTC/USDT", "ETH/USDT"],
        supported_timeframes  = ["1m", "5m"],
        requires_streams      = ["candles"],
        reconnect             = True,
        reconnect_delay       = 3.0,
        max_reconnect_delay   = 30.0,
        max_reconnect_attempts= 10,
        log_level             = logging.DEBUG,
    )

    component = MarketDataComponent(config)
    await component.run()


if __name__ == "__main__":
    asyncio.run(main())
