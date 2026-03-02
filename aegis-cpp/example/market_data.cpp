#include "aegis/client.hpp"

#include <atomic>
#include <chrono>
#include <csignal>
#include <iostream>
#include <memory>
#include <stop_token>
#include <thread>

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

class MarketDataHandler : public aegis::ComponentHandler {
public:
    void on_configure(
        const std::string&              socket_path,
        const std::vector<std::string>& topics
    ) override {
        std::cout << "[MarketData] Configuring — socket=" << socket_path << "\n";
        // Connect to data stream here
    }

    void on_running(std::stop_token stop) override {
        std::cout << "[MarketData] Running — starting data worker\n";
        int tick = 0;
        while (!stop.stop_requested()) {
            ++tick;
            std::cout << "[MarketData] Tick #" << tick << " — processing data...\n";
            std::this_thread::sleep_for(std::chrono::seconds(5));
        }
        std::cout << "[MarketData] Data worker stopped\n";
    }

    void on_ping() override {
        std::cout << "[MarketData] PING received\n";
    }

    void on_shutdown() override {
        std::cout << "[MarketData] Releasing resources\n";
    }

    void on_error(const std::string& code, const std::string& message) override {
        std::cerr << "[MarketData] Error — code=" << code << " message=" << message << "\n";
    }
};

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

static aegis::Client* g_client = nullptr;

int main() {
    aegis::Config cfg;
    cfg.socket_path              = "/tmp/aegis_components.sock";
    cfg.session_token            = "YOUR_SESSION_TOKEN_HERE";
    cfg.component_name           = "market_data";
    cfg.version                  = "0.1.0";
    cfg.supported_symbols        = {"BTC/USDT", "ETH/USDT"};
    cfg.supported_timeframes     = {"1m", "5m"};
    cfg.requires_streams         = {"candles"};
    cfg.max_reconnect_attempts   = 10;

    auto client = std::make_unique<aegis::Client>(
        cfg,
        std::make_unique<MarketDataHandler>()
    );

    g_client = client.get();

    // Handle Ctrl-C
    std::signal(SIGINT,  [](int) { if (g_client) g_client->stop(); });
    std::signal(SIGTERM, [](int) { if (g_client) g_client->stop(); });

    try {
        client->run();
    } catch (const std::exception& e) {
        std::cerr << "Component stopped: " << e.what() << "\n";
        return 1;
    }
    return 0;
}
