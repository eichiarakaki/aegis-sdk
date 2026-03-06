"""
Example: MarketDataComponent
============================
Demonstrates a component that reads its config from Aegis-injected
environment variables and subscribes to market data topics.

Launch via Aegis (recommended):
    aegis session attach <session_id> --path ./my_component

Manual launch (development only):
    AEGIS_SESSION_TOKEN=<token> AEGIS_COMPONENT_SOCKET=/tmp/aegis-components.sock \
        python example.py
"""

import asyncio
import logging
import os

from aegis_component import AegisComponent, ComponentConfig, ComponentState


class MarketDataComponent(AegisComponent):

    def __init__(self, config: ComponentConfig) -> None:
        super().__init__(config)
        self._stream_socket: str       = ""
        self._topics:        list[str] = []
        self._worker_task: asyncio.Task | None = None

    async def on_configure(self, socket_path: str, topics: list[str]) -> None:
        self._stream_socket = socket_path
        self._topics        = topics
        self.log.info(
            "Configuration received — socket=%s  topics=%s", socket_path, topics
        )
        # Connect to the per-session data stream socket here.
        # reader, writer = await asyncio.open_unix_connection(socket_path)

    async def on_running(self) -> None:
        self._worker_task = asyncio.create_task(self._data_worker())

    async def on_shutdown(self) -> None:
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self.log.info("Resources released")

    async def _data_worker(self) -> None:
        tick = 0
        while True:
            tick += 1
            self.log.info("Tick #%d — topics=%s", tick, self._topics)
            await self.send_state_update(ComponentState.WAITING)
            await asyncio.sleep(2)
            await self.send_state_update(ComponentState.RUNNING)
            await asyncio.sleep(3)


if __name__ == "__main__":
    # ComponentConfig.from_env() reads AEGIS_SESSION_TOKEN and
    # AEGIS_COMPONENT_SOCKET automatically — no hardcoded values needed.
    config = ComponentConfig.from_env(
        component_name       = "market_data",
        version              = "0.1.0",
        supported_symbols    = ["BTCUSDT", "ETHUSDT"],
        supported_timeframes = ["1m", "5m", "15m"],
        requires_streams     = ["klines", "trades"],
        reconnect              = True,
        reconnect_delay        = 3.0,
        max_reconnect_delay    = 30.0,
        max_reconnect_attempts = 10,
        log_level              = logging.DEBUG,
    )

    print("ENV CHECK:")
    print("  AEGIS_SESSION_TOKEN =", os.environ.get("AEGIS_SESSION_TOKEN"))
    print("  AEGIS_COMPONENT_SOCKET =", os.environ.get("AEGIS_COMPONENT_SOCKET"))  
    print("  AEGIS_COMPONENT_ID =", os.environ.get("AEGIS_COMPONENT_ID"))

    asyncio.run(MarketDataComponent(config).run())