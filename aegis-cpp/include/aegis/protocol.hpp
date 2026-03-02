#pragma once

#include <nlohmann/json.hpp>
#include <chrono>
#include <optional>
#include <string>

namespace aegis {

using json = nlohmann::json;

constexpr auto PROTOCOL_VERSION = "0.1";

enum class MessageType { Control, Lifecycle, Config, Error, Heartbeat, Data };
enum class Command {
    Register, Registered, StateUpdate, Shutdown,
    Ack, Nack, Configure, Configured,
    Ping, Pong, RuntimeError, RegistrationFailed
};
enum class ComponentState {
    Init, Registered, Initializing, Ready, Configured,
    Running, Waiting, Error, Finished, Shutdown
};

std::string to_string(MessageType t);
std::string to_string(Command c);
std::string to_string(ComponentState s);
ComponentState state_from_string(const std::string& s);

struct Envelope {
    std::string              protocol_version;
    std::string              message_id;
    std::optional<std::string> correlation_id;
    std::string              timestamp;
    std::string              source;
    std::string              target;
    MessageType              msg_type;
    Command                  command;
    json                     payload;

    static Envelope make(
        MessageType type,
        Command     cmd,
        std::string source,
        json        payload
    );

    Envelope& with_correlation(const std::string& id);

    json to_json() const;
    static Envelope from_json(const json& j);
};

} // namespace aegis
