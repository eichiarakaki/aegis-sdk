package aegis

import (
	"time"

	"github.com/google/uuid"
)

const ProtocolVersion = "0.1"

// MessageType classifies messages in the Aegis protocol.
type MessageType string

const (
	MessageTypeControl   MessageType = "CONTROL"
	MessageTypeLifecycle MessageType = "LIFECYCLE"
	MessageTypeConfig    MessageType = "CONFIG"
	MessageTypeError     MessageType = "ERROR"
	MessageTypeHeartbeat MessageType = "HEARTBEAT"
	MessageTypeData      MessageType = "DATA"
)

// Command represents a specific protocol command.
type Command string

const (
	CommandRegister           Command = "REGISTER"
	CommandRegistered         Command = "REGISTERED"
	CommandStateUpdate        Command = "STATE_UPDATE"
	CommandShutdown           Command = "SHUTDOWN"
	CommandACK                Command = "ACK"
	CommandNACK               Command = "NACK"
	CommandConfigure          Command = "CONFIGURE"
	CommandConfigured         Command = "CONFIGURED"
	CommandPing               Command = "PING"
	CommandPong               Command = "PONG"
	CommandRuntimeError       Command = "RUNTIME_ERROR"
	CommandRegistrationFailed Command = "REGISTRATION_FAILED"
)

// ComponentState represents the lifecycle state of a component.
type ComponentState string

const (
	StateInit         ComponentState = "INIT"
	StateRegistered   ComponentState = "REGISTERED"
	StateInitializing ComponentState = "INITIALIZING"
	StateReady        ComponentState = "READY"
	StateConfigured   ComponentState = "CONFIGURED"
	StateRunning      ComponentState = "RUNNING"
	StateWaiting      ComponentState = "WAITING"
	StateError        ComponentState = "ERROR"
	StateFinished     ComponentState = "FINISHED"
	StateShutdown     ComponentState = "SHUTDOWN"
)

// Envelope is the standard message wrapper for all Aegis protocol messages.
type Envelope struct {
	ProtocolVersion string                 `json:"protocol_version"`
	MessageID       string                 `json:"message_id"`
	CorrelationID   *string                `json:"correlation_id"`
	Timestamp       string                 `json:"timestamp"`
	Source          string                 `json:"source"`
	Target          string                 `json:"target"`
	Type            MessageType            `json:"type"`
	Command         Command                `json:"command"`
	Payload         map[string]interface{} `json:"payload"`
}

// newEnvelope creates a new Envelope with generated ID and timestamp.
func newEnvelope(msgType MessageType, cmd Command, source string, payload map[string]interface{}) *Envelope {
	return &Envelope{
		ProtocolVersion: ProtocolVersion,
		MessageID:       uuid.New().String(),
		CorrelationID:   nil,
		Timestamp:       time.Now().UTC().Format(time.RFC3339),
		Source:          source,
		Target:          "aegis",
		Type:            msgType,
		Command:         cmd,
		Payload:         payload,
	}
}

func (e *Envelope) withCorrelation(id string) *Envelope {
	e.CorrelationID = &id
	return e
}
