package config

import (
	"strings"
	"testing"
)

func TestLoadRequiresSecrets(t *testing.T) {
	t.Setenv("JWT_SECRET", "")
	t.Setenv("API_KEY", "")
	t.Setenv("DATABASE_URL", "")
	t.Setenv("PYTHON_AGENT_URL", "")
	if _, err := Load(); err == nil {
		t.Fatal("expected Load to fail without secrets")
	}
}

func TestLoadRejectsWeakSecrets(t *testing.T) {
	t.Setenv("JWT_SECRET", "too-short")
	t.Setenv("API_KEY", "also-too-short")
	t.Setenv("DATABASE_URL", "postgres://x")
	t.Setenv("PYTHON_AGENT_URL", "http://x")
	_, err := Load()
	if err == nil {
		t.Fatal("expected weak JWT_SECRET to be rejected")
	}
	if !strings.Contains(err.Error(), "JWT_SECRET") {
		t.Errorf("expected JWT_SECRET error, got %v", err)
	}
}

func TestLoadSuccess(t *testing.T) {
	t.Setenv("JWT_SECRET", strings.Repeat("a", 32))
	t.Setenv("API_KEY", strings.Repeat("b", 16))
	t.Setenv("DATABASE_URL", "postgres://user:pass@host/db")
	t.Setenv("PYTHON_AGENT_URL", "http://python-agent:8000")
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.JWTTTL <= 0 {
		t.Errorf("expected positive JWT TTL")
	}
	if cfg.RateLimitRPS <= 0 {
		t.Errorf("expected positive RPS, got %f", cfg.RateLimitRPS)
	}
}
