package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	aegis "github.com/eichiarakaki/aegis-component-go"
)

func main() {
	cfg := aegis.DefaultConfig(
		"/tmp/aegis_components.sock",
		"YOUR_SESSION_TOKEN_HERE",
		"market_data",
	)
	cfg.Version              = "0.1.0"
	cfg.SupportedSymbols    = []string{"BTC/USDT", "ETH/USDT"}
	cfg.SupportedTimeframes = []string{"1m", "5m"}
	cfg.RequiresStreams      = []string{"candles"}
	cfg.MaxReconnectAttempts = 10

	// Use a cancelable context — cancelling it triggers a graceful shutdown.
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	// worker holds the running goroutine so OnShutdown can stop it.
	var workerCancel context.CancelFunc

	handlers := aegis.Handlers{
		OnConfigure: func(ctx context.Context, socketPath string, topics []string) error {
			log.Printf("Configuring — socket=%s topics=%v", socketPath, topics)
			// In a real component, connect to the data stream here:
			// conn, err := net.Dial("unix", socketPath)
			return nil
		},

		OnRunning: func(ctx context.Context) error {
			workerCtx, wcancel := context.WithCancel(ctx)
			workerCancel = wcancel
			go dataWorker(workerCtx)
			return nil
		},

		OnPing: func(ctx context.Context) {
			log.Println("PING received")
		},

		OnShutdown: func(ctx context.Context) {
			log.Println("Shutdown hook — releasing resources")
			if workerCancel != nil {
				workerCancel()
			}
		},

		OnError: func(ctx context.Context, code, message string) {
			log.Printf("Error from Aegis — code=%s message=%s", code, message)
		},
	}

	component := aegis.New(cfg, handlers)

	log.Println("Starting market_data component...")
	if err := component.Run(ctx); err != nil {
		fmt.Fprintf(os.Stderr, "component stopped: %v\n", err)
		os.Exit(1)
	}
}

// dataWorker simulates processing market data ticks.
func dataWorker(ctx context.Context) {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	tick := 0
	for {
		select {
		case <-ctx.Done():
			log.Println("Data worker stopped")
			return
		case <-ticker.C:
			tick++
			log.Printf("Tick #%d — processing data...", tick)
		}
	}
}
