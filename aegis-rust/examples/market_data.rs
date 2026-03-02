use aegis_component::{AegisError, Component, ComponentHandler, ComponentState, Config, Result};
use tokio::sync::CancellationToken;
use tracing::info;

// ---------------------------------------------------------------------------
// Handler implementation
// ---------------------------------------------------------------------------

struct MarketDataHandler;

impl ComponentHandler for MarketDataHandler {
    async fn on_configure(&self, socket_path: String, topics: Vec<String>) -> Result<()> {
        info!("Configuring — socket={} topics={:?}", socket_path, topics);
        // Connect to the data stream socket here:
        // let stream = tokio::net::UnixStream::connect(&socket_path).await?;
        Ok(())
    }

    async fn on_running(&self, shutdown: CancellationToken) -> Result<()> {
        info!("Component running — starting data worker");
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(std::time::Duration::from_secs(5));
            let mut tick = 0u64;
            loop {
                tokio::select! {
                    _ = shutdown.cancelled() => {
                        info!("Data worker stopped");
                        break;
                    }
                    _ = interval.tick() => {
                        tick += 1;
                        info!("Tick #{} — processing data...", tick);
                    }
                }
            }
        });
        Ok(())
    }

    async fn on_ping(&self) {
        info!("PING received");
    }

    async fn on_shutdown(&self) {
        info!("Releasing resources");
    }

    async fn on_error(&self, code: String, message: String) {
        tracing::error!("Aegis error — code={} message={}", code, message);
    }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

#[tokio::main]
async fn main() -> std::result::Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter("aegis_component=debug,market_data=info")
        .init();

    let mut cfg = Config::new(
        "/tmp/aegis_components.sock",
        "YOUR_SESSION_TOKEN_HERE",
        "market_data",
    );
    cfg.version              = "0.1.0".into();
    cfg.supported_symbols    = vec!["BTC/USDT".into(), "ETH/USDT".into()];
    cfg.supported_timeframes = vec!["1m".into(), "5m".into()];
    cfg.requires_streams     = vec!["candles".into()];
    cfg.max_reconnect_attempts = 10;

    let component = Component::new(cfg, MarketDataHandler);

    // Run until ctrl-c
    tokio::select! {
        res = component.run() => {
            if let Err(e) = res {
                eprintln!("Component stopped with error: {}", e);
                std::process::exit(1);
            }
        }
        _ = tokio::signal::ctrl_c() => {
            info!("Ctrl-C received, shutting down");
        }
    }

    Ok(())
}
