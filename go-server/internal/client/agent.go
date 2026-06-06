// Package client provides an HTTP client for the Python agent service with
// retries, timeouts, and a basic circuit breaker.
package client

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sync"
	"sync/atomic"
	"time"

	"github.com/cenkalti/backoff/v4"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"

	"github.com/Neeraj8180/ecom-agent/go-server/internal/models"
)

// breakerState is the simple closed/open/half-open state machine.
type breakerState int32

const (
	stateClosed breakerState = iota
	stateOpen
	stateHalfOpen
)

// AgentClient is a resilient HTTP client targeting the Python agent service.
type AgentClient struct {
	baseURL string
	http    *http.Client

	mu                 sync.Mutex
	consecutiveFails   int
	state              atomic.Int32 // breakerState
	openedAt           time.Time
	failThreshold      int
	openCooldown       time.Duration
}

// NewAgentClient constructs a client with sensible defaults.
func NewAgentClient(baseURL string, timeout time.Duration) *AgentClient {
	return &AgentClient{
		baseURL:       baseURL,
		http:          &http.Client{Timeout: timeout},
		failThreshold: 5,
		openCooldown:  20 * time.Second,
	}
}

// ProcessQuery forwards a chat message to the Python agent.
func (c *AgentClient) ProcessQuery(ctx context.Context, req *models.AgentRequest) (*models.AgentResponse, error) {
	return c.post(ctx, "/process_query", req)
}

// Replay asks the agent to re-run a stored session.
func (c *AgentClient) Replay(ctx context.Context, sessionID string) (*models.AgentResponse, error) {
	return c.post(ctx, "/replay", map[string]string{"session_id": sessionID})
}

// Health pings the agent.
func (c *AgentClient) Health(ctx context.Context) error {
	if !c.allow() {
		return errors.New("circuit breaker open")
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodGet, c.baseURL+"/health", nil)
	if err != nil {
		return err
	}
	resp, err := c.http.Do(httpReq)
	if err != nil {
		c.recordFailure()
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 500 {
		c.recordFailure()
		return fmt.Errorf("agent unhealthy: %d", resp.StatusCode)
	}
	c.recordSuccess()
	return nil
}

func (c *AgentClient) post(ctx context.Context, path string, payload any) (*models.AgentResponse, error) {
	if !c.allow() {
		return nil, errors.New("circuit breaker open: python agent unavailable")
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("marshal payload: %w", err)
	}

	var resp *models.AgentResponse
	op := func() error {
		httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+path, bytes.NewReader(body))
		if err != nil {
			return backoff.Permanent(err)
		}
		httpReq.Header.Set("Content-Type", "application/json")
		// Propagate W3C trace context to Python service.
		otel.GetTextMapPropagator().Inject(ctx, propagation.HeaderCarrier(httpReq.Header))

		httpResp, err := c.http.Do(httpReq)
		if err != nil {
			return err
		}
		defer httpResp.Body.Close()

		if httpResp.StatusCode >= 500 {
			return fmt.Errorf("upstream status %d", httpResp.StatusCode)
		}
		if httpResp.StatusCode >= 400 {
			// 4xx is a permanent client error - do not retry.
			data, _ := io.ReadAll(httpResp.Body)
			return backoff.Permanent(fmt.Errorf("upstream client error %d: %s", httpResp.StatusCode, string(data)))
		}

		var out models.AgentResponse
		if err := json.NewDecoder(httpResp.Body).Decode(&out); err != nil {
			return fmt.Errorf("decode response: %w", err)
		}
		resp = &out
		return nil
	}

	bo := backoff.WithContext(
		backoff.WithMaxRetries(backoff.NewExponentialBackOff(), 2), // total 3 attempts
		ctx,
	)
	if err := backoff.Retry(op, bo); err != nil {
		c.recordFailure()
		return nil, err
	}
	c.recordSuccess()
	return resp, nil
}

// --- circuit breaker -------------------------------------------------------

func (c *AgentClient) allow() bool {
	state := breakerState(c.state.Load())
	if state == stateClosed {
		return true
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if breakerState(c.state.Load()) == stateOpen && time.Since(c.openedAt) > c.openCooldown {
		c.state.Store(int32(stateHalfOpen))
		return true
	}
	return breakerState(c.state.Load()) == stateHalfOpen
}

func (c *AgentClient) recordSuccess() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.consecutiveFails = 0
	c.state.Store(int32(stateClosed))
}

func (c *AgentClient) recordFailure() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.consecutiveFails++
	if c.consecutiveFails >= c.failThreshold {
		c.state.Store(int32(stateOpen))
		c.openedAt = time.Now()
	}
}
