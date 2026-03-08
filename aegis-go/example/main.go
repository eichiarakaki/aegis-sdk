package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	aegis "github.com/eichiarakaki/aegis-sdk/aegis-go/aegis"
)

func main() {
	cfg := aegis.DefaultConfig("market_data")
	cfg.Version = "0.1.0"
	cfg.SupportedSymbols = []string{"BTCUSDT", "ETHUSDT"}
	cfg.SupportedTimeframes = []string{"1m", "5m", "15m"}
	cfg.RequiresStreams = []string{"klines", "trades"}
	cfg.MaxReconnectAttempts = 10

	component := aegis.New(cfg, aegis.Handlers{})
	log := cfg.Logger

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	var workerCancel context.CancelFunc
	var socketPath string

	component.Handlers().OnConfigure = func(ctx context.Context, sp string, topics []string) error {
		socketPath = sp
		log.Infof("Configuring — socket=%s topics=%v", sp, topics)
		return nil
	}

	component.Handlers().OnRunning = func(ctx context.Context) error {
		workerCtx, wcancel := context.WithCancel(ctx)
		workerCancel = wcancel
		go streamWorker(workerCtx, component, socketPath, log)
		return nil
	}

	component.Handlers().OnShutdown = func(ctx context.Context) {
		log.Infof("Shutdown — releasing resources")
		if workerCancel != nil {
			workerCancel()
		}
	}

	component.Handlers().OnError = func(ctx context.Context, code, message string) {
		log.Errorf("Error from Aegis — code=%s message=%s", code, message)
	}

	log.Infof("Starting market_data component...")
	if err := component.Run(ctx); err != nil {
		fmt.Fprintf(os.Stderr, "component stopped: %v\n", err)
		os.Exit(1)
	}
}

func streamWorker(ctx context.Context, c *aegis.Component, socketPath string, log aegis.Logger) {
	if socketPath == "" {
		log.Errorf("No socket path received — cannot open stream")
		return
	}

	var stream *aegis.DataStream
	for {
		var err error
		stream, err = c.OpenStream(ctx, socketPath)
		if err == nil {
			break
		}
		log.Warnf("Stream connect error: %v — retrying in 1s...", err)
		select {
		case <-ctx.Done():
			return
		case <-time.After(time.Second):
		}
	}
	defer stream.Close()

	log.Infof("Stream opened successfully — subscribed to: %v", stream.Topics)

	for {
		msg, err := stream.Next(ctx)
		if err != nil {
			if ctx.Err() != nil {
				return
			}
			log.Errorf("Stream read error: %v", err)
			return
		}
		handleMessage(msg, log)
	}
}

func handleMessage(msg *aegis.StreamEnvelope, log aegis.Logger) {
	raw, _ := json.MarshalIndent(msg, "", "  ")
	log.Infof("Received — topic=%s ts=%d\n%s", msg.Topic, msg.Ts, string(raw))
}
