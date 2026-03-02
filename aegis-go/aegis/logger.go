package aegis

import (
	"fmt"
	"log"
	"os"
)

// Logger is the logging interface used by the library.
// Implement it to plug in your own logger (zap, slog, zerolog, etc.).
type Logger interface {
	Debugf(format string, args ...interface{})
	Infof(format string, args ...interface{})
	Warnf(format string, args ...interface{})
	Errorf(format string, args ...interface{})
}

// defaultLogger is a stdlib-based Logger implementation.
type defaultLogger struct {
	debug *log.Logger
	info  *log.Logger
	warn  *log.Logger
	err   *log.Logger
}

// NewDefaultLogger returns a Logger that writes to stdout/stderr.
func NewDefaultLogger(name string) Logger {
	prefix := fmt.Sprintf("[aegis.%s] ", name)
	flags  := log.Ldate | log.Ltime
	return &defaultLogger{
		debug: log.New(os.Stdout, prefix+"DEBUG ", flags),
		info:  log.New(os.Stdout, prefix+"INFO  ", flags),
		warn:  log.New(os.Stdout, prefix+"WARN  ", flags),
		err:   log.New(os.Stderr, prefix+"ERROR ", flags),
	}
}

func (l *defaultLogger) Debugf(format string, args ...interface{}) { l.debug.Printf(format, args...) }
func (l *defaultLogger) Infof(format string, args ...interface{})  { l.info.Printf(format, args...) }
func (l *defaultLogger) Warnf(format string, args ...interface{})  { l.warn.Printf(format, args...) }
func (l *defaultLogger) Errorf(format string, args ...interface{}) { l.err.Printf(format, args...) }

// NoopLogger discards all log output.
type NoopLogger struct{}

func (NoopLogger) Debugf(_ string, _ ...interface{}) {}
func (NoopLogger) Infof(_ string, _ ...interface{})  {}
func (NoopLogger) Warnf(_ string, _ ...interface{})  {}
func (NoopLogger) Errorf(_ string, _ ...interface{}) {}
