#include "aegis/client.hpp"

#include <chrono>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace aegis {

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static void log_info(const std::string& component, const std::string& msg) {
    std::cout << "[INFO]  [" << component << "] " << msg << "\n";
}
static void log_warn(const std::string& component, const std::string& msg) {
    std::cout << "[WARN]  [" << component << "] " << msg << "\n";
}
static void log_error(const std::string& component, const std::string& msg) {
    std::cerr << "[ERROR] [" << component << "] " << msg << "\n";
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

Client::Client(Config cfg, std::unique_ptr<ComponentHandler> handler)
    : cfg_(std::move(cfg)), handler_(std::move(handler))
{}

Client::~Client() {
    stop();
    if (fd_ >= 0) ::close(fd_);
}

void Client::stop() {
    running_ = false;
    stop_source_.request_stop();
}

ComponentState Client::current_state() const {
    return state_.load();
}

void Client::run() {
    int   attempts = 0;
    float delay    = static_cast<float>(cfg_.reconnect_delay_s);

    while (true) {
        try {
            run_once();
            return; // clean exit
        } catch (const std::runtime_error& e) {
            std::string what = e.what();
            if (what.rfind("REGISTRATION_FAILED", 0) == 0) {
                log_error(cfg_.component_name, "Registration failed (will not retry): " + what);
                throw;
            }
            log_warn(cfg_.component_name, std::string("Disconnected: ") + what);
        }

        if (!cfg_.reconnect) throw std::runtime_error("reconnect disabled");

        ++attempts;
        if (cfg_.max_reconnect_attempts > 0 && attempts >= cfg_.max_reconnect_attempts) {
            throw std::runtime_error(
                "max reconnect attempts (" + std::to_string(attempts) + ") reached"
            );
        }

        log_info(cfg_.component_name,
            "Reconnecting in " + std::to_string(static_cast<int>(delay)) +
            "s (attempt " + std::to_string(attempts) + ")..."
        );

        std::this_thread::sleep_for(std::chrono::seconds(static_cast<int>(delay)));
        delay = std::min(delay * 2.0f, static_cast<float>(cfg_.max_reconnect_delay_s));
    }
}

void Client::run_once() {
    started_at_ = std::chrono::steady_clock::now();

    // Create Unix domain socket
    fd_ = ::socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd_ < 0) throw std::runtime_error("socket() failed");

    struct sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    ::strncpy(addr.sun_path, cfg_.socket_path.c_str(), sizeof(addr.sun_path) - 1);

    log_info(cfg_.component_name, "Connecting to " + cfg_.socket_path);

    if (::connect(fd_, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) < 0) {
        ::close(fd_); fd_ = -1;
        throw std::runtime_error("connect() failed: " + std::string(::strerror(errno)));
    }

    log_info(cfg_.component_name, "Connected");

    do_register();
    running_ = true;
    message_loop();

    ::close(fd_); fd_ = -1;
}

void Client::do_register() {
    json payload = {
        {"session_token",  cfg_.session_token},
        {"component_name", cfg_.component_name},
        {"version",        cfg_.version},
        {"capabilities", {
            {"supported_symbols",    cfg_.supported_symbols},
            {"supported_timeframes", cfg_.supported_timeframes},
            {"requires_streams",     cfg_.requires_streams},
        }},
    };

    auto env = Envelope::make(MessageType::Lifecycle, Command::Register, source(), payload);
    send_envelope(env);

    auto resp = recv_envelope();
    if (resp.command != Command::Registered) {
        throw std::runtime_error("REGISTRATION_FAILED: unexpected command " + to_string(resp.command));
    }

    component_id = resp.payload.value("component_id", "");
    session_id   = resp.payload.value("session_id",   "");
    state_.store(ComponentState::Registered);

    log_info(cfg_.component_name,
        "Registered — component_id=" + component_id + " session_id=" + session_id
    );
}

void Client::message_loop() {
    // Set read timeout of 35s
    struct timeval tv{35, 0};
    ::setsockopt(fd_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    while (running_) {
        Envelope env;
        try {
            env = recv_envelope();
        } catch (const std::exception& e) {
            log_warn(cfg_.component_name, std::string("Read error: ") + e.what());
            break;
        }

        switch (env.msg_type) {
            case MessageType::Heartbeat: handle_heartbeat(env);  break;
            case MessageType::Config:    handle_config(env);     break;
            case MessageType::Lifecycle:
                if (handle_lifecycle(env)) return;
                break;
            case MessageType::Error:
                if (handle_error_msg(env)) {
                    throw std::runtime_error("non-recoverable error from Aegis");
                }
                break;
            default:
                log_warn(cfg_.component_name, "Unknown message type: " + to_string(env.msg_type));
        }
    }

    graceful_shutdown();
}

void Client::handle_heartbeat(const Envelope& env) {
    if (env.command != Command::Ping) return;
    handler_->on_ping();

    auto now    = std::chrono::steady_clock::now();
    auto uptime = std::chrono::duration_cast<std::chrono::seconds>(now - started_at_).count();

    json payload = {
        {"state",          to_string(state_.load())},
        {"uptime_seconds", uptime},
    };
    auto pong = Envelope::make(MessageType::Heartbeat, Command::Pong, source(), payload)
        .with_correlation(env.message_id);
    send_envelope(pong);
}

void Client::handle_config(const Envelope& env) {
    if (env.command != Command::Configure) return;

    std::string sock = env.payload.value("data_stream_socket", "");
    std::vector<std::string> topics;
    if (env.payload.contains("topics") && env.payload["topics"].is_array())
        topics = env.payload["topics"].get<std::vector<std::string>>();

    log_info(cfg_.component_name, "Configuring — socket=" + sock);

    handler_->on_configure(sock, topics);
    send_ack(env.message_id);

    send_state_update(ComponentState::Configured);
    send_state_update(ComponentState::Running);

    log_info(cfg_.component_name, "Component is now RUNNING");

    // Launch on_running in a background jthread
    stop_source_ = std::stop_source{};
    worker_thread_ = std::make_unique<std::jthread>(
        [this](std::stop_token st) { handler_->on_running(st); }
    );
}

bool Client::handle_lifecycle(const Envelope& env) {
    if (env.command == Command::Shutdown) {
        log_info(cfg_.component_name, "Shutdown requested by Aegis");
        send_ack(env.message_id);
        graceful_shutdown();
        return true;
    }
    return false;
}

bool Client::handle_error_msg(const Envelope& env) {
    std::string code    = env.payload.value("code",    "UNKNOWN");
    std::string message = env.payload.value("message", "");
    bool recoverable    = env.payload.value("recoverable", false);

    log_error(cfg_.component_name, "Error — code=" + code + " message=" + message);
    handler_->on_error(code, message);
    return !recoverable;
}

void Client::graceful_shutdown() {
    log_info(cfg_.component_name, "Shutting down...");

    if (worker_thread_) {
        stop_source_.request_stop();
        worker_thread_->join();
        worker_thread_.reset();
    }

    handler_->on_shutdown();

    try {
        auto env = Envelope::make(MessageType::Lifecycle, Command::Shutdown, source(), json::object());
        send_envelope(env);
    } catch (...) {}

    state_.store(ComponentState::Shutdown);
    log_info(cfg_.component_name, "Shutdown complete");
}

void Client::send_state_update(ComponentState state, const std::string& message) {
    json payload = {{"state", to_string(state)}};
    if (!message.empty()) payload["message"] = message;
    auto env = Envelope::make(MessageType::Lifecycle, Command::StateUpdate, source(), payload);
    send_envelope(env);
    state_.store(state);
}

void Client::send_error(const std::string& code, const std::string& message, bool recoverable) {
    json payload = {{"code", code}, {"message", message}, {"recoverable", recoverable}};
    auto env = Envelope::make(MessageType::Error, Command::RuntimeError, source(), payload);
    send_envelope(env);
}

void Client::send_ack(const std::string& correlation_id) {
    json payload = {{"status", "ok"}};
    auto env = Envelope::make(MessageType::Control, Command::Ack, source(), payload)
        .with_correlation(correlation_id);
    send_envelope(env);
}

void Client::send_envelope(const Envelope& env) {
    std::string data = env.to_json().dump() + "\n";
    std::lock_guard<std::mutex> lock(send_mutex_);
    ::write(fd_, data.c_str(), data.size());
}

Envelope Client::recv_envelope() {
    std::string line;
    char ch;
    while (::read(fd_, &ch, 1) == 1) {
        if (ch == '\n') break;
        line += ch;
    }
    if (line.empty()) throw std::runtime_error("connection closed");
    return Envelope::from_json(json::parse(line));
}

std::string Client::source() const {
    return "component:" + cfg_.component_name;
}

} // namespace aegis
