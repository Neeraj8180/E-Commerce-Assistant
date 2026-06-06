// Package config loads server configuration from environment variables.
//
// Production safety:
//   * JWT_SECRET, API_KEY, and DATABASE_URL are MANDATORY. The process refuses
//     to start without them so an operator cannot accidentally run with the
//     example values from a committed file.
//   * JWT_SECRET must be at least 32 bytes of entropy to discourage weak keys.
package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config aggregates all server configuration. Values come from environment
// variables. No insecure defaults are provided for secrets.
type Config struct {
	Port               int
	JWTSecret          string
	JWTIssuer          string
	JWTTTL             time.Duration
	APIKey             string
	RateLimitRPS       float64
	RateLimitBurst     int
	PythonAgentURL     string
	PythonAgentTimeout time.Duration
	DatabaseURL        string
	OTelEndpoint       string
	OTelServiceName    string
	LogLevel           string
	Environment        string
}

// Load reads configuration from environment variables.
func Load() (*Config, error) {
	jwtSecret := strings.TrimSpace(os.Getenv("JWT_SECRET"))
	if len(jwtSecret) < 32 {
		return nil, fmt.Errorf("JWT_SECRET must be set and at least 32 characters (got %d)", len(jwtSecret))
	}
	apiKey := strings.TrimSpace(os.Getenv("API_KEY"))
	if len(apiKey) < 16 {
		return nil, fmt.Errorf("API_KEY must be set and at least 16 characters (got %d)", len(apiKey))
	}
	dbURL := strings.TrimSpace(os.Getenv("DATABASE_URL"))
	if dbURL == "" {
		return nil, fmt.Errorf("DATABASE_URL must be set")
	}
	pyURL := strings.TrimSpace(os.Getenv("PYTHON_AGENT_URL"))
	if pyURL == "" {
		return nil, fmt.Errorf("PYTHON_AGENT_URL must be set")
	}

	cfg := &Config{
		Port:               getEnvInt("GO_SERVER_PORT", 8080),
		JWTSecret:          jwtSecret,
		JWTIssuer:          getEnv("JWT_ISSUER", "ecom-agent"),
		JWTTTL:             time.Duration(getEnvInt("JWT_TTL_MINUTES", 60)) * time.Minute,
		APIKey:             apiKey,
		RateLimitRPS:       getEnvFloat("RATE_LIMIT_RPS", 10),
		RateLimitBurst:     getEnvInt("RATE_LIMIT_BURST", 20),
		PythonAgentURL:     pyURL,
		PythonAgentTimeout: time.Duration(getEnvInt("PYTHON_AGENT_TIMEOUT_SECONDS", 30)) * time.Second,
		DatabaseURL:        dbURL,
		OTelEndpoint:       getEnv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
		OTelServiceName:    getEnv("OTEL_SERVICE_NAME", "go-server"),
		LogLevel:           getEnv("LOG_LEVEL", "info"),
		Environment:        getEnv("ENVIRONMENT", "development"),
	}
	return cfg, nil
}

func getEnv(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return fallback
}

func getEnvInt(key string, fallback int) int {
	if v, ok := os.LookupEnv(key); ok {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return fallback
}

func getEnvFloat(key string, fallback float64) float64 {
	if v, ok := os.LookupEnv(key); ok {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return fallback
}
