package aegis

import (
	"context"
	"time"
)

// Config holds all configuration for an Aegis component.
type Config struct {
	// Connection
	SocketPath string

	// Identity
	SessionToken  string
	ComponentName string
	Version       string

	// Capabilities
	SupportedSymbols    []string
	SupportedTimeframes []string
	RequiresStreams      []string

	// Reconnection
	Reconnect             bool
	ReconnectDelay        time.Duration
	MaxReconnectDelay     time.Duration
	MaxReconnectAttempts  int // 0 = unlimited

	// Logging
	Logger Logger
}

// DefaultConfig returns a Config with sensible reconnection defaults.
func DefaultConfig(socketPath, sessionToken, componentName string) Config {
	return Config{
		SocketPath:           socketPath,
		SessionToken:         sessionToken,
		ComponentName:        componentName,
		Version:              "0.1.0",
		Reconnect:            true,
		ReconnectDelay:       3 * time.Second,
		MaxReconnectDelay:    60 * time.Second,
		MaxReconnectAttempts: 0,
		Logger:               NewDefaultLogger(componentName),
	}
}

// Handlers groups all event callbacks for a component.
// All fields are optional — set only what you need.
type Handlers struct {
	// OnConfigure is called when Aegis sends a CONFIGURE message.
	// socket is the data stream Unix socket path; topics are the subscribed topics.
	OnConfigure func(ctx context.Context, socket string, topics []string) error

	// OnRunning is called after the component transitions to RUNNING.
	// Start long-running goroutines here; they should respect ctx cancellation.
	OnRunning func(ctx context.Context) error

	// OnPing is called on every PING received before the PONG is sent.
	OnPing func(ctx context.Context)

	// OnShutdown is called just before the component disconnects.
	// Use it to release resources.
	OnShutdown func(ctx context.Context)

	// OnError is called when Aegis sends an ERROR message.
	OnError func(ctx context.Context, code, message string)
}
