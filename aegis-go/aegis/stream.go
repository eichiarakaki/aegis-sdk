package aegis

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"net"
)

// StreamEnvelope is the message received from the data stream socket.
// Matches the orchestrator.Envelope published to NATS.
type StreamEnvelope struct {
	SessionID string          `json:"session_id"`
	Topic     string          `json:"topic"`
	Ts        int64           `json:"ts"`
	Data      json.RawMessage `json:"data"`
}

// StreamHandshake is sent by the client to identify itself on the data stream socket.
type StreamHandshake struct {
	ComponentID  string `json:"component_id"`
	SessionToken string `json:"session_token"`
}

// StreamHandshakeResponse is received after a successful handshake.
type StreamHandshakeResponse struct {
	Status  string   `json:"status"`
	Message string   `json:"message,omitempty"`
	Topics  []string `json:"topics,omitempty"`
}

// DataStream is a connected data stream session.
// Obtain one via Component.OpenStream inside OnConfigure or OnRunning.
type DataStream struct {
	conn   net.Conn
	reader *bufio.Reader
	Topics []string // topics confirmed by the server
}

// OpenStream connects to the data stream Unix socket and completes the handshake.
// Call this inside OnConfigure or OnRunning with the socketPath received from aegisd.
func (c *Component) OpenStream(ctx context.Context, socketPath string) (*DataStream, error) {
	if c.ComponentID == "" || c.SessionID == "" {
		return nil, fmt.Errorf("stream: component not yet registered")
	}

	conn, err := net.Dial("unix", socketPath)
	if err != nil {
		return nil, fmt.Errorf("stream: connect %s: %w", socketPath, err)
	}

	enc := json.NewEncoder(conn)
	dec := json.NewDecoder(bufio.NewReader(conn))

	// Send handshake.
	hs := StreamHandshake{
		ComponentID:  c.ComponentID,
		SessionToken: c.SessionID,
	}
	if err := enc.Encode(hs); err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("stream: send handshake: %w", err)
	}

	// Read handshake response.
	var resp StreamHandshakeResponse
	if err := dec.Decode(&resp); err != nil {
		_ = conn.Close()
		return nil, fmt.Errorf("stream: read handshake response: %w", err)
	}

	if resp.Status != "ok" {
		_ = conn.Close()
		return nil, fmt.Errorf("stream: handshake rejected: %s", resp.Message)
	}

	c.log.Infof("Data stream open — topics=%v", resp.Topics)

	return &DataStream{
		conn:   conn,
		reader: bufio.NewReader(conn),
		Topics: resp.Topics,
	}, nil
}

// Next reads and returns the next StreamEnvelope from the data stream.
// Blocks until a message arrives, the context is cancelled, or the connection closes.
func (s *DataStream) Next(ctx context.Context) (*StreamEnvelope, error) {
	// Use a goroutine to make the blocking read cancellable via context.
	type result struct {
		env *StreamEnvelope
		err error
	}
	ch := make(chan result, 1)

	go func() {
		line, err := s.reader.ReadBytes('\n')
		if err != nil {
			ch <- result{nil, err}
			return
		}
		var env StreamEnvelope
		if err := json.Unmarshal(line, &env); err != nil {
			ch <- result{nil, fmt.Errorf("stream: unmarshal: %w", err)}
			return
		}
		ch <- result{&env, nil}
	}()

	select {
	case <-ctx.Done():
		_ = s.conn.Close() // unblock the goroutine
		return nil, ctx.Err()
	case r := <-ch:
		return r.env, r.err
	}
}

// Close closes the data stream connection.
func (s *DataStream) Close() error {
	return s.conn.Close()
}
