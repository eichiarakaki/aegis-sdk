#pragma once

#include "aegis/component.hpp"
#include "aegis/protocol.hpp"

#include <atomic>
#include <memory>
#include <mutex>
#include <stop_token>
#include <string>
#include <thread>

namespace aegis {

/// Aegis component client.
///
/// Construct with a Config and a ComponentHandler, then call run().
class Client {
public:
    explicit Client(Config cfg, std::unique_ptr<ComponentHandler> handler);
    ~Client();

    /// Connect, register, and enter the message loop.
    /// Blocks until a non-recoverable error or stop() is called.
    void run();

    /// Request a graceful stop from another thread.
    void stop();

    /// Send a STATE_UPDATE message to Aegis.
    void send_state_update(ComponentState state, const std::string& message = "");

    /// Report a runtime error to Aegis.
    void send_error(const std::string& code, const std::string& message, bool recoverable = true);

    ComponentState current_state() const;

    std::string component_id;
    std::string session_id;

private:
    void run_once();
    void do_register();
    void message_loop();

    void handle_heartbeat(const Envelope& env);
    void handle_config(const Envelope& env);
    bool handle_lifecycle(const Envelope& env); // returns true → stop loop
    bool handle_error_msg(const Envelope& env); // returns true → non-recoverable

    void graceful_shutdown();
    void send_ack(const std::string& correlation_id);
    void send_envelope(const Envelope& env);
    Envelope recv_envelope();

    std::string source() const;

    Config                              cfg_;
    std::unique_ptr<ComponentHandler>   handler_;
    std::atomic<ComponentState>         state_{ComponentState::Init};

    int  fd_{-1};   // Unix domain socket fd
    bool running_{false};

    std::mutex              send_mutex_;
    std::chrono::steady_clock::time_point started_at_;

    std::stop_source          stop_source_;
    std::unique_ptr<std::jthread> worker_thread_;
};

} // namespace aegis
