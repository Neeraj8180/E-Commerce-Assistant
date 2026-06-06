package models

import (
	"time"

	"github.com/Neeraj8180/ecom-agent/go-server/internal/auth"
)

type LoginRequest struct {
	Email    string `json:"email"    binding:"required,email,max=254"`
	Password string `json:"password" binding:"required,min=8,max=128"`
}

type LoginResponse struct {
	AccessToken string    `json:"access_token"`
	TokenType   string    `json:"token_type"`
	ExpiresIn   int64     `json:"expires_in"`
	User        auth.User `json:"user"`
}

// ChatRequest is the inbound /chat payload. Identity is taken from the
// authenticated principal, never from the body.
type ChatRequest struct {
	SessionID string                 `json:"session_id" binding:"omitempty,session"`
	Message   string                 `json:"message"    binding:"required,min=1,max=4000,safetext"`
	Context   map[string]interface{} `json:"context,omitempty"`
}

type ChatResponse struct {
	SessionID string                 `json:"session_id"`
	Intent    string                 `json:"intent"`
	Reply     string                 `json:"reply"`
	Outcome   string                 `json:"outcome"`
	Escalated bool                   `json:"escalated"`
	ToolsUsed []string               `json:"tools_used,omitempty"`
	Metadata  map[string]interface{} `json:"metadata,omitempty"`
	LatencyMS int64                  `json:"latency_ms"`
	RequestID string                 `json:"request_id"`
}

type AgentRequest struct {
	UserID    string                 `json:"user_id"`
	SessionID string                 `json:"session_id"`
	Message   string                 `json:"message"`
	Context   map[string]interface{} `json:"context,omitempty"`
	RequestID string                 `json:"request_id"`
}

type AgentResponse struct {
	SessionID string                 `json:"session_id"`
	Intent    string                 `json:"intent"`
	Reply     string                 `json:"reply"`
	Outcome   string                 `json:"outcome"`
	Escalated bool                   `json:"escalated"`
	ToolsUsed []string               `json:"tools_used"`
	Metadata  map[string]interface{} `json:"metadata"`
}

type ReplayRequest struct {
	SessionID string `json:"session_id" binding:"required,session"`
}

type HealthResponse struct {
	Status       string            `json:"status"`
	Service      string            `json:"service"`
	Time         time.Time         `json:"time"`
	Dependencies map[string]string `json:"dependencies"`
}

type ErrorResponse struct {
	Error     string `json:"error"`
	Detail    string `json:"detail,omitempty"`
	RequestID string `json:"request_id,omitempty"`
}
