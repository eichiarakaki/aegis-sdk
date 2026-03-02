#pragma once

#include <chrono>
#include <functional>
#include <string>
#include <vector>

namespace aegis {

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

struct Config {
    // Connection
    std::string socket_path;

    // Identity
    std::string session_token;
    std::string component_name;
    std::string version = "0.1.0";

    // Capabilities
    std::vector<std::string> supported_symbols;
    std::vector<std::string> supported_timeframes;
    std::vector<std::string> requires_streams;

    // Reconnection
    bool        reconnect               = true;
    int         reconnect_delay_s       = 3;
    int         max_reconnect_delay_s   = 60;
    int         max_reconnect_attempts  = 0; // 0 = unlimited
};

// ---------------------------------------------------------------------------
// ComponentHandler — interface
// ---------------------------------------------------------------------------

/// Subclass this to implement your component logic.
class ComponentHandler {
public:
    virtual ~ComponentHandler() = default;

    /// Called when Aegis sends CONFIGURE.
    virtual void on_configure(
        const std::string&              socket_path,
        const std::vector<std::string>& topics
    ) {}

    /// Called after the component transitions to RUNNING.
    /// Should start background threads that check the stop_token.
    virtual void on_running(std::stop_token stop) {}

    /// Called on every PING before the PONG is sent.
    virtual void on_ping() {}

    /// Called just before the component disconnects.
    virtual void on_shutdown() {}

    /// Called when Aegis sends a non-recoverable ERROR.
    virtual void on_error(const std::string& code, const std::string& message) {}
};

} // namespace aegis
