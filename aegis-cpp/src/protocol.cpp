#include "aegis/protocol.hpp"

#include <chrono>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <uuid/uuid.h>

namespace aegis {

static std::string generate_uuid() {
    uuid_t id;
    uuid_generate(id);
    char buf[37];
    uuid_unparse_lower(id, buf);
    return buf;
}

static std::string utc_now() {
    auto now = std::chrono::system_clock::now();
    auto t   = std::chrono::system_clock::to_time_t(now);
    std::ostringstream ss;
    ss << std::put_time(std::gmtime(&t), "%Y-%m-%dT%H:%M:%SZ");
    return ss.str();
}

std::string to_string(MessageType t) {
    switch (t) {
        case MessageType::Control:   return "CONTROL";
        case MessageType::Lifecycle: return "LIFECYCLE";
        case MessageType::Config:    return "CONFIG";
        case MessageType::Error:     return "ERROR";
        case MessageType::Heartbeat: return "HEARTBEAT";
        case MessageType::Data:      return "DATA";
    }
    return "UNKNOWN";
}

std::string to_string(Command c) {
    switch (c) {
        case Command::Register:           return "REGISTER";
        case Command::Registered:         return "REGISTERED";
        case Command::StateUpdate:        return "STATE_UPDATE";
        case Command::Shutdown:           return "SHUTDOWN";
        case Command::Ack:                return "ACK";
        case Command::Nack:               return "NACK";
        case Command::Configure:          return "CONFIGURE";
        case Command::Configured:         return "CONFIGURED";
        case Command::Ping:               return "PING";
        case Command::Pong:               return "PONG";
        case Command::RuntimeError:       return "RUNTIME_ERROR";
        case Command::RegistrationFailed: return "REGISTRATION_FAILED";
    }
    return "UNKNOWN";
}

std::string to_string(ComponentState s) {
    switch (s) {
        case ComponentState::Init:         return "INIT";
        case ComponentState::Registered:   return "REGISTERED";
        case ComponentState::Initializing: return "INITIALIZING";
        case ComponentState::Ready:        return "READY";
        case ComponentState::Configured:   return "CONFIGURED";
        case ComponentState::Running:      return "RUNNING";
        case ComponentState::Waiting:      return "WAITING";
        case ComponentState::Error:        return "ERROR";
        case ComponentState::Finished:     return "FINISHED";
        case ComponentState::Shutdown:     return "SHUTDOWN";
    }
    return "UNKNOWN";
}

ComponentState state_from_string(const std::string& s) {
    if (s == "INIT")         return ComponentState::Init;
    if (s == "REGISTERED")   return ComponentState::Registered;
    if (s == "INITIALIZING") return ComponentState::Initializing;
    if (s == "READY")        return ComponentState::Ready;
    if (s == "CONFIGURED")   return ComponentState::Configured;
    if (s == "RUNNING")      return ComponentState::Running;
    if (s == "WAITING")      return ComponentState::Waiting;
    if (s == "ERROR")        return ComponentState::Error;
    if (s == "FINISHED")     return ComponentState::Finished;
    if (s == "SHUTDOWN")     return ComponentState::Shutdown;
    throw std::runtime_error("Unknown state: " + s);
}

static MessageType msg_type_from_string(const std::string& s) {
    if (s == "CONTROL")   return MessageType::Control;
    if (s == "LIFECYCLE") return MessageType::Lifecycle;
    if (s == "CONFIG")    return MessageType::Config;
    if (s == "ERROR")     return MessageType::Error;
    if (s == "HEARTBEAT") return MessageType::Heartbeat;
    if (s == "DATA")      return MessageType::Data;
    throw std::runtime_error("Unknown message type: " + s);
}

static Command command_from_string(const std::string& s) {
    if (s == "REGISTER")            return Command::Register;
    if (s == "REGISTERED")          return Command::Registered;
    if (s == "STATE_UPDATE")        return Command::StateUpdate;
    if (s == "SHUTDOWN")            return Command::Shutdown;
    if (s == "ACK")                 return Command::Ack;
    if (s == "NACK")                return Command::Nack;
    if (s == "CONFIGURE")           return Command::Configure;
    if (s == "CONFIGURED")          return Command::Configured;
    if (s == "PING")                return Command::Ping;
    if (s == "PONG")                return Command::Pong;
    if (s == "RUNTIME_ERROR")       return Command::RuntimeError;
    if (s == "REGISTRATION_FAILED") return Command::RegistrationFailed;
    throw std::runtime_error("Unknown command: " + s);
}

Envelope Envelope::make(MessageType type, Command cmd, std::string src, json payload) {
    Envelope e;
    e.protocol_version = PROTOCOL_VERSION;
    e.message_id       = generate_uuid();
    e.timestamp        = utc_now();
    e.source           = std::move(src);
    e.target           = "aegis";
    e.msg_type         = type;
    e.command          = cmd;
    e.payload          = std::move(payload);
    return e;
}

Envelope& Envelope::with_correlation(const std::string& id) {
    correlation_id = id;
    return *this;
}

json Envelope::to_json() const {
    json j = {
        {"protocol_version", protocol_version},
        {"message_id",       message_id},
        {"correlation_id",   correlation_id ? json(*correlation_id) : json(nullptr)},
        {"timestamp",        timestamp},
        {"source",           source},
        {"target",           target},
        {"type",             to_string(msg_type)},
        {"command",          to_string(command)},
        {"payload",          payload},
    };
    return j;
}

Envelope Envelope::from_json(const json& j) {
    Envelope e;
    e.protocol_version = j.value("protocol_version", "");
    e.message_id       = j.value("message_id", "");
    if (j.contains("correlation_id") && !j["correlation_id"].is_null())
        e.correlation_id = j["correlation_id"].get<std::string>();
    e.timestamp = j.value("timestamp", "");
    e.source    = j.value("source",    "");
    e.target    = j.value("target",    "");
    e.msg_type  = msg_type_from_string(j.value("type",    ""));
    e.command   = command_from_string( j.value("command", ""));
    e.payload   = j.value("payload",   json::object());
    return e;
}

} // namespace aegis
