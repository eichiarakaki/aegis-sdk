package aegis

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"sync"
	"sync/atomic"
	"time"
)

// Component is the Aegis component client.
// Create one with New, then call Run to connect and start the lifecycle.
type Component struct {
	cfg      Config
	handlers Handlers

	// Identity (populated after registration)
	ComponentID string
	SessionID   string
	State       atomic.Value // ComponentState

	conn   net.Conn
	reader *bufio.Reader
	sendMu sync.Mutex

	startedAt time.Time
	log       Logger
}

// New creates a new Component with the given configuration and handlers.
func New(cfg Config, handlers Handlers) *Component {
	if cfg.Logger == nil {
		cfg.Logger = NewDefaultLogger(cfg.ComponentName)
	}
	c := &Component{
		cfg:      cfg,
		handlers: handlers,
		log:      cfg.Logger,
	}
	c.State.Store(StateInit)
	return c
}

// Run connects to Aegis, registers the component, and enters the message loop.
// It blocks until the context is cancelled or a non-recoverable error occurs.
// Reconnection is handled automatically if cfg.Reconnect is true.
func (c *Component) Run(ctx context.Context) error {
	attempts := 0
	delay := c.cfg.ReconnectDelay

	for {
		if err := ctx.Err(); err != nil {
			return err
		}

		runErr := c.runOnce(ctx)

		if errors.Is(runErr, context.Canceled) || errors.Is(runErr, context.DeadlineExceeded) {
			return runErr
		}

		var regErr *RegistrationError
		if errors.As(runErr, &regErr) {
			return runErr
		}

		if !c.cfg.Reconnect {
			return runErr
		}

		attempts++
		if c.cfg.MaxReconnectAttempts > 0 && attempts >= c.cfg.MaxReconnectAttempts {
			return fmt.Errorf("max reconnect attempts (%d) reached: %w", attempts, runErr)
		}

		c.log.Warnf("Disconnected (%v) — reconnecting in %s (attempt %d)...", runErr, delay, attempts)

		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(delay):
		}

		delay = minDuration(delay*2, c.cfg.MaxReconnectDelay)
	}
}

// SendStateUpdate sends a STATE_UPDATE message to Aegis.
func (c *Component) SendStateUpdate(ctx context.Context, state ComponentState, message string) error {
	payload := map[string]interface{}{"state": string(state)}
	if message != "" {
		payload["message"] = message
	}
	env := newEnvelope(MessageTypeLifecycle, CommandStateUpdate, c.source(), payload)
	if err := c.send(env); err != nil {
		return err
	}
	c.State.Store(state)
	return nil
}

// SendError reports a runtime error to Aegis.
func (c *Component) SendError(code, message string, recoverable bool) error {
	env := newEnvelope(MessageTypeError, CommandRuntimeError, c.source(), map[string]interface{}{
		"code":        code,
		"message":     message,
		"recoverable": recoverable,
	})
	return c.send(env)
}

// CurrentState returns the current ComponentState.
func (c *Component) CurrentState() ComponentState {
	return c.State.Load().(ComponentState)
}

// Handlers returns a pointer to the component's handler set so callers
// can override individual callbacks after New() but before Run().
func (c *Component) Handlers() *Handlers {
	return &c.handlers
}

// ---------------------------------------------------------------------------
// Internal
// ---------------------------------------------------------------------------

func (c *Component) runOnce(ctx context.Context) error {
	c.startedAt = time.Now()

	c.log.Infof("Connecting to %s", c.cfg.SocketPath)
	conn, err := net.Dial("unix", c.cfg.SocketPath)
	if err != nil {
		return fmt.Errorf("connect: %w", err)
	}
	c.conn = conn
	c.reader = bufio.NewReader(conn)
	defer c.closeConn()

	c.log.Infof("Connected")

	// Handshake: REGISTER → REGISTERED → STATE_UPDATE(INITIALIZING) → STATE_UPDATE(READY) → CONFIGURE → ACK → RUNNING
	if err := c.register(ctx); err != nil {
		return err
	}

	return c.messageLoop(ctx)
}

// register executes the full handshake sequence:
//  1. Send REGISTER (with pre-assigned component_id if available)
//  2. Receive REGISTERED
//  3. Send STATE_UPDATE(READY) — signals aegisd to send CONFIGURE
func (c *Component) register(ctx context.Context) error {
	env := newEnvelope(MessageTypeLifecycle, CommandRegister, c.source(), map[string]interface{}{
		"session_token":  c.cfg.SessionToken,
		"component_name": c.cfg.ComponentName,
		"component_id":   c.cfg.ComponentID, // empty string is fine — daemon generates one if missing
		"version":        c.cfg.Version,
		"capabilities": map[string]interface{}{
			"supported_symbols":    c.cfg.SupportedSymbols,
			"supported_timeframes": c.cfg.SupportedTimeframes,
			"requires_streams":     c.cfg.RequiresStreams,
		},
	})

	if err := c.send(env); err != nil {
		return fmt.Errorf("send register: %w", err)
	}

	resp, err := c.recv()
	if err != nil {
		return fmt.Errorf("recv registered: %w", err)
	}
	if resp.Command != CommandRegistered {
		return &RegistrationError{Msg: fmt.Sprintf("unexpected response: %s", resp.Command)}
	}

	c.ComponentID = fmt.Sprintf("%v", resp.Payload["component_id"])
	c.SessionID = fmt.Sprintf("%v", resp.Payload["session_id"])
	c.State.Store(StateRegistered)
	c.log.Infof("Registered — component_id=%s session_id=%s", c.ComponentID, c.SessionID)

	// INITIALIZING — component performs its own startup work (load models, open files, etc.)
	// aegisd WaitForReady expects this state before READY.
	if err := c.SendStateUpdate(ctx, StateInitializing, ""); err != nil {
		return fmt.Errorf("send STATE_UPDATE(INITIALIZING): %w", err)
	}
	c.log.Debugf("Sent STATE_UPDATE(INITIALIZING)")

	// Wait for ACK from aegisd before advancing to READY.
	if _, err := c.recv(); err != nil {
		return fmt.Errorf("recv ACK(INITIALIZING): %w", err)
	}
	c.log.Debugf("ACK(INITIALIZING) received")

	// READY — signals aegisd to proceed with CONFIGURE.
	if err := c.SendStateUpdate(ctx, StateReady, ""); err != nil {
		return fmt.Errorf("send STATE_UPDATE(READY): %w", err)
	}
	c.log.Debugf("Sent STATE_UPDATE(READY) — waiting for CONFIGURE")

	// Wait for ACK from aegisd — CONFIGURE follows immediately after.
	if _, err := c.recv(); err != nil {
		return fmt.Errorf("recv ACK(READY): %w", err)
	}
	c.log.Debugf("ACK(READY) received")

	return nil
}

func (c *Component) messageLoop(ctx context.Context) error {
	c.log.Debugf("Entering message loop")

	for {
		if err := ctx.Err(); err != nil {
			_ = c.gracefulShutdown(ctx)
			return err
		}

		_ = c.conn.SetReadDeadline(time.Now().Add(35 * time.Second))

		env, err := c.recv()
		if err != nil {
			return fmt.Errorf("recv: %w", err)
		}

		c.log.Debugf("Received type=%s command=%s", env.Type, env.Command)

		switch env.Type {
		case MessageTypeHeartbeat:
			c.handleHeartbeat(ctx, env)
		case MessageTypeConfig:
			c.handleConfig(ctx, env)
		case MessageTypeLifecycle:
			if stop := c.handleLifecycle(ctx, env); stop {
				return nil
			}
		case MessageTypeError:
			if stop := c.handleErrorMsg(ctx, env); stop {
				return fmt.Errorf("non-recoverable error from Aegis: %s", env.Payload["code"])
			}
		default:
			c.log.Warnf("Unknown message type: %s", env.Type)
		}
	}
}

func (c *Component) handleHeartbeat(ctx context.Context, env *Envelope) {
	if env.Command != CommandPing {
		return
	}
	if c.handlers.OnPing != nil {
		c.handlers.OnPing(ctx)
	}

	uptime := int64(time.Since(c.startedAt).Seconds())
	pong := newEnvelope(MessageTypeHeartbeat, CommandPong, c.source(), map[string]interface{}{
		"state":          string(c.CurrentState()),
		"uptime_seconds": uptime,
	})
	pong.withCorrelation(env.MessageID)

	if err := c.send(pong); err != nil {
		c.log.Warnf("Failed to send PONG: %v", err)
		return
	}
	c.log.Debugf("Sent PONG (uptime=%ds)", uptime)
}

// handleConfig processes CONFIGURE from aegisd:
//  1. Call OnConfigure handler
//  2. ACK the message
//  3. Send STATE_UPDATE(CONFIGURED) — aegisd waits for this before proceeding
//  4. Send STATE_UPDATE(RUNNING)
//  5. Call OnRunning handler in a goroutine
func (c *Component) handleConfig(ctx context.Context, env *Envelope) {
	if env.Command != CommandConfigure {
		return
	}

	sockPath, _ := env.Payload["data_stream_socket"].(string)
	topicsRaw, _ := env.Payload["topics"].([]interface{})
	topics := make([]string, 0, len(topicsRaw))
	for _, t := range topicsRaw {
		if s, ok := t.(string); ok {
			topics = append(topics, s)
		}
	}

	c.log.Infof("Configuring — socket=%s topics=%v", sockPath, topics)

	if c.handlers.OnConfigure != nil {
		if err := c.handlers.OnConfigure(ctx, sockPath, topics); err != nil {
			c.log.Errorf("OnConfigure error: %v", err)
			_ = c.SendError("CONFIGURE_FAILED", err.Error(), true)
			return
		}
	}

	// ACK the CONFIGURE message — aegisd WaitForConfigACK expects this.
	_ = c.sendACK(env.MessageID)

	// STATE_UPDATE(CONFIGURED) — wait for ACK before advancing.
	if err := c.SendStateUpdate(ctx, StateConfigured, ""); err != nil {
		c.log.Errorf("Failed to send STATE_UPDATE(CONFIGURED): %v", err)
		return
	}
	if _, err := c.recv(); err != nil {
		c.log.Errorf("Failed to recv ACK(CONFIGURED): %v", err)
		return
	}
	c.log.Debugf("ACK(CONFIGURED) received")

	// STATE_UPDATE(RUNNING) — wait for ACK before entering message loop.
	if err := c.SendStateUpdate(ctx, StateRunning, ""); err != nil {
		c.log.Errorf("Failed to send STATE_UPDATE(RUNNING): %v", err)
		return
	}
	if _, err := c.recv(); err != nil {
		c.log.Errorf("Failed to recv ACK(RUNNING): %v", err)
		return
	}
	c.log.Debugf("ACK(RUNNING) received")

	c.log.Infof("Component is now RUNNING")

	if c.handlers.OnRunning != nil {
		go func() {
			if err := c.handlers.OnRunning(ctx); err != nil {
				c.log.Errorf("OnRunning error: %v", err)
			}
		}()
	}
}

// handleLifecycle returns true if the message loop should stop.
func (c *Component) handleLifecycle(ctx context.Context, env *Envelope) bool {
	switch env.Command {
	case CommandShutdown:
		c.log.Infof("Shutdown requested by Aegis")
		_ = c.sendACK(env.MessageID)
		_ = c.gracefulShutdown(ctx)
		return true
	case CommandACK:
		c.log.Debugf("ACK received")
	default:
		c.log.Warnf("Unknown lifecycle command: %s", env.Command)
	}
	return false
}

// handleErrorMsg returns true if the error is non-recoverable.
func (c *Component) handleErrorMsg(ctx context.Context, env *Envelope) bool {
	code, _ := env.Payload["code"].(string)
	message, _ := env.Payload["message"].(string)
	recoverable, _ := env.Payload["recoverable"].(bool)

	c.log.Errorf("Error from Aegis — code=%s message=%s recoverable=%v", code, message, recoverable)

	if c.handlers.OnError != nil {
		c.handlers.OnError(ctx, code, message)
	}

	return !recoverable
}

func (c *Component) gracefulShutdown(ctx context.Context) error {
	c.log.Infof("Shutting down...")

	if c.handlers.OnShutdown != nil {
		c.handlers.OnShutdown(ctx)
	}

	env := newEnvelope(MessageTypeLifecycle, CommandShutdown, c.source(), map[string]interface{}{})
	_ = c.send(env)

	c.State.Store(StateShutdown)
	c.log.Infof("Shutdown complete")
	return nil
}

func (c *Component) sendACK(correlationID string) error {
	ack := newEnvelope(MessageTypeControl, CommandACK, c.source(), map[string]interface{}{"status": "ok"})
	ack.withCorrelation(correlationID)
	return c.send(ack)
}

func (c *Component) send(env *Envelope) error {
	c.sendMu.Lock()
	defer c.sendMu.Unlock()
	return json.NewEncoder(c.conn).Encode(env)
}

func (c *Component) recv() (*Envelope, error) {
	var env Envelope
	if err := json.NewDecoder(c.reader).Decode(&env); err != nil {
		return nil, err
	}
	return &env, nil
}

func (c *Component) closeConn() {
	if c.conn != nil {
		_ = c.conn.Close()
	}
}

func (c *Component) source() string {
	if c.ComponentID != "" {
		return "component:" + c.ComponentID
	}
	return "component:" + c.cfg.ComponentName
}

func minDuration(a, b time.Duration) time.Duration {
	if a < b {
		return a
	}
	return b
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

// RegistrationError is returned when the Aegis handshake fails fatally.
// The component will not retry after this error.
type RegistrationError struct {
	Msg string
}

func (e *RegistrationError) Error() string {
	return "registration error: " + e.Msg
}
