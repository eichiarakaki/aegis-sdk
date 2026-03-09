//! Basic example: a component that connects to Aegis, receives market data,
//! and resets cleanly on session restart (REBORN).

use libaegis::{AegisError, Component, ComponentHandler, Config, Result};
use tokio_util::sync::CancellationToken;
use tracing::info;

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

struct MarketDataHandler;

impl ComponentHandler for MarketDataHandler {
    async fn on_configure(&self, socket_path: String, topics: Vec<String>) -> Result<()> {
        info!("configure — socket={} topics={:?}", socket_path, topics);
        // Open the data stream socket here, e.g.:
        // let mut stream = libaegis::DataStream::connect(&socket_path, &component_id, &session_id).await?;
        Ok(())
    }

    async fn on_running(&self, shutdown: CancellationToken) -> Result<()> {
        info!("running — starting data worker");

        // Spawn the processing loop. It keeps running across session restarts —
        // REBORN does not cancel this token or call on_running again.
        // Reset per-run state in on_reborn() instead.
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(std::time::Duration::from_secs(5));
            let mut tick = 0u64;
            loop {
                tokio::select! {
                    _ = shutdown.cancelled() => {
                        info!("data worker stopped");
                        break;
                    }
                    _ = interval.tick() => {
                        tick += 1;
                        info!("tick #{} — processing data...", tick);
                    }
                }
            }
        });

        Ok(())
    }

    async fn on_reborn(&self) {
        // Called when Aegis restarts the session (REBORN command).
        // Reset ALL state from the previous run here — counters, positions,
        // buffers, etc. on_running is NOT called again; the same task keeps
        // running and will receive data from the new orchestrator run.
        info!("reborn — resetting per-run state");
    }

    async fn on_ping(&self) {
        info!("ping");
    }

    async fn on_shutdown(&self) {
        info!("shutdown — releasing resources");
    }

    async fn on_error(&self, code: String, message: String) {
        tracing::error!("aegis error — code={} message={}", code, message);
    }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() -> std::result::Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter("libaegis=debug,market_data=info")
        .init();

    let socket_path   = std::env::var("AEGIS_SOCKET")
        .unwrap_or_else(|_| "/tmp/aegis-components.sock".into());
    let session_token = std::env::var("AEGIS_SESSION_TOKEN")
        .unwrap_or_default();

    let mut cfg = Config::new(socket_path, session_token, "market_data");
    cfg.version                = "0.1.0".into();
    cfg.supported_symbols      = vec!["BTCUSDT".into(), "ETHUSDT".into()];
    cfg.supported_timeframes   = vec!["1m".into(), "5m".into()];
    cfg.requires_streams       = vec!["aggTrades".into(), "klines".into()];
    cfg.max_reconnect_attempts = 10;

    let component = Component::new(cfg, MarketDataHandler);

    tokio::select! {
        res = component.run() => {
            if let Err(e) = res {
                eprintln!("component stopped with error: {e}");
                std::process::exit(1);
            }
        }
        _ = tokio::signal::ctrl_c() => {
            info!("ctrl-c — shutting down");
        }
    }

    Ok(())
}