package handlers

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/go-playground/validator/v10"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/Neeraj8180/ecom-agent/go-server/internal/client"
	"github.com/Neeraj8180/ecom-agent/go-server/internal/middleware"
	"github.com/Neeraj8180/ecom-agent/go-server/internal/models"
	"github.com/Neeraj8180/ecom-agent/go-server/internal/validation"
)

type Deps struct {
	Agent        *client.AgentClient
	DB           *pgxpool.Pool
	Logger       *slog.Logger
	AgentTimeout time.Duration
}

// Chat is the main user-facing endpoint. The user identity is taken from
// the JWT (or X-User-ID for service tokens) — clients cannot impersonate
// another user.
func Chat(d *Deps) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		rid := middleware.RequestIDFrom(c)

		var req models.ChatRequest
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, models.ErrorResponse{
				Error: "invalid request", Detail: humanizeBindErr(err), RequestID: rid,
			})
			return
		}
		cleanCtx, err := validation.CleanContext(req.Context)
		if err != nil {
			c.JSON(http.StatusBadRequest, models.ErrorResponse{
				Error: "invalid context", Detail: err.Error(), RequestID: rid,
			})
			return
		}

		userID := middleware.UserEmailFrom(c)
		if userID == "" {
			userID = middleware.UserIDFrom(c)
		}
		if userID == "" {
			c.JSON(http.StatusUnauthorized, models.ErrorResponse{Error: "missing authenticated user", RequestID: rid})
			return
		}
		if req.SessionID == "" {
			req.SessionID = uuid.NewString()
		}

		agentReq := &models.AgentRequest{
			UserID:    userID,
			SessionID: req.SessionID,
			Message:   req.Message,
			Context:   cleanCtx,
			RequestID: rid,
		}

		timeout := d.AgentTimeout
		if timeout <= 0 {
			timeout = 30 * time.Second
		}
		ctx, cancel := context.WithTimeout(c.Request.Context(), timeout)
		defer cancel()

		agentResp, err := d.Agent.ProcessQuery(ctx, agentReq)
		if err != nil {
			d.Logger.ErrorContext(ctx, "agent call failed",
				slog.String("request_id", rid),
				slog.String("session_id", req.SessionID),
				slog.String("error", err.Error()),
			)
			c.JSON(http.StatusBadGateway, models.ErrorResponse{
				Error: "agent unavailable", Detail: err.Error(), RequestID: rid,
			})
			return
		}

		c.JSON(http.StatusOK, models.ChatResponse{
			SessionID: agentResp.SessionID,
			Intent:    agentResp.Intent,
			Reply:     agentResp.Reply,
			Outcome:   agentResp.Outcome,
			Escalated: agentResp.Escalated,
			ToolsUsed: agentResp.ToolsUsed,
			Metadata:  agentResp.Metadata,
			LatencyMS: time.Since(start).Milliseconds(),
			RequestID: rid,
		})
	}
}

func Replay(d *Deps) gin.HandlerFunc {
	return func(c *gin.Context) {
		rid := middleware.RequestIDFrom(c)
		var req models.ReplayRequest
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, models.ErrorResponse{
				Error: "invalid request", Detail: humanizeBindErr(err), RequestID: rid,
			})
			return
		}
		timeout := d.AgentTimeout
		if timeout <= 0 {
			timeout = 30 * time.Second
		}
		ctx, cancel := context.WithTimeout(c.Request.Context(), timeout)
		defer cancel()
		resp, err := d.Agent.Replay(ctx, req.SessionID)
		if err != nil {
			c.JSON(http.StatusBadGateway, models.ErrorResponse{
				Error: "replay failed", Detail: err.Error(), RequestID: rid,
			})
			return
		}
		c.JSON(http.StatusOK, resp)
	}
}

func Health(d *Deps) gin.HandlerFunc {
	return func(c *gin.Context) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 3*time.Second)
		defer cancel()

		deps := map[string]string{}

		if err := d.Agent.Health(ctx); err != nil {
			deps["python_agent"] = "down: " + err.Error()
		} else {
			deps["python_agent"] = "up"
		}

		if d.DB != nil {
			if err := d.DB.Ping(ctx); err != nil {
				deps["postgres"] = "down: " + err.Error()
			} else {
				deps["postgres"] = "up"
			}
		} else {
			deps["postgres"] = "not configured"
		}

		status := "ok"
		for _, v := range deps {
			if v != "up" {
				status = "degraded"
				break
			}
		}
		code := http.StatusOK
		if status != "ok" {
			code = http.StatusServiceUnavailable
		}
		c.JSON(code, models.HealthResponse{
			Status:       status,
			Service:      "go-server",
			Time:         time.Now().UTC(),
			Dependencies: deps,
		})
	}
}

// humanizeBindErr produces a compact, user-safe rendering of a validation
// error. Field-level messages name the field and the rule that failed so
// clients can fix the request without leaking internal field types.
func humanizeBindErr(err error) string {
	var ve validator.ValidationErrors
	if errors.As(err, &ve) {
		parts := make([]string, 0, len(ve))
		for _, f := range ve {
			parts = append(parts, f.Field()+": "+f.Tag())
		}
		out := ""
		for i, p := range parts {
			if i > 0 {
				out += "; "
			}
			out += p
		}
		return out
	}
	return err.Error()
}
