// Package middleware contains Gin middleware: request ID, logging, auth,
// rate limiting, and metrics recording.
package middleware

import (
	"crypto/subtle"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"golang.org/x/time/rate"

	"github.com/Neeraj8180/ecom-agent/go-server/internal/auth"
	"github.com/Neeraj8180/ecom-agent/go-server/internal/observability"
)

const (
	ctxRequestID = "request_id"
	ctxUserID    = "user_id"
	ctxUserEmail = "user_email"
	ctxUserRole  = "user_role"
	headerReqID  = "X-Request-ID"
)

// RequestID injects a request id (generated or propagated from header).
// Inbound IDs are length-checked to prevent log-bloat attacks.
func RequestID() gin.HandlerFunc {
	return func(c *gin.Context) {
		rid := strings.TrimSpace(c.GetHeader(headerReqID))
		if rid == "" || len(rid) > 128 {
			rid = uuid.NewString()
		}
		c.Set(ctxRequestID, rid)
		c.Writer.Header().Set(headerReqID, rid)
		c.Next()
	}
}

// MaxBodyBytes caps the request body to prevent memory exhaustion.
func MaxBodyBytes(max int64) gin.HandlerFunc {
	return func(c *gin.Context) {
		if c.Request.Body != nil {
			c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, max)
		}
		c.Next()
	}
}

// StructuredLogger logs each request as a single JSON line.
func StructuredLogger(logger *slog.Logger, metrics *observability.Metrics, serviceName string) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		metrics.InFlight.Inc()
		defer metrics.InFlight.Dec()

		c.Next()

		latency := time.Since(start)
		status := c.Writer.Status()
		path := c.FullPath()
		if path == "" {
			path = c.Request.URL.Path
		}

		logger.LogAttrs(c.Request.Context(), slog.LevelInfo, "request",
			slog.String("service", serviceName),
			slog.String("method", c.Request.Method),
			slog.String("path", path),
			slog.Int("status", status),
			slog.Int64("latency_ms", latency.Milliseconds()),
			slog.String("request_id", c.GetString(ctxRequestID)),
			slog.String("user_id", c.GetString(ctxUserID)),
			slog.String("user_email", c.GetString(ctxUserEmail)),
			slog.String("client_ip", c.ClientIP()),
		)

		statusStr := strconv.Itoa(status)
		metrics.RequestDuration.WithLabelValues(serviceName, c.Request.Method, path, statusStr).Observe(latency.Seconds())
		metrics.RequestTotal.WithLabelValues(serviceName, c.Request.Method, path, statusStr).Inc()
	}
}

// Auth accepts either:
//   * Authorization: Bearer <JWT>  - signed by the auth service
//   * X-API-Key: <key>             - constant-time compared to configured API_KEY
//                                    (service-to-service / evaluation harness)
//
// On success the authenticated user id, email, and role are placed on the
// Gin context for downstream handlers and the structured logger.
func Auth(svc *auth.Service, apiKey string) gin.HandlerFunc {
	apiKeyBytes := []byte(apiKey)
	return func(c *gin.Context) {
		if k := c.GetHeader("X-API-Key"); k != "" {
			if subtle.ConstantTimeCompare([]byte(k), apiKeyBytes) != 1 {
				c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid api key"})
				return
			}
			// Service tokens may carry an X-User-ID for downstream attribution.
			if uid := c.GetHeader("X-User-ID"); uid != "" {
				c.Set(ctxUserID, uid)
				c.Set(ctxUserEmail, uid)
			}
			c.Set(ctxUserRole, "service")
			c.Next()
			return
		}

		header := c.GetHeader("Authorization")
		if !strings.HasPrefix(header, "Bearer ") {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "missing bearer token"})
			return
		}
		tokenStr := strings.TrimPrefix(header, "Bearer ")

		user, err := svc.VerifyToken(tokenStr)
		if err != nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "invalid token"})
			return
		}
		c.Set(ctxUserID, user.ID)
		c.Set(ctxUserEmail, user.Email)
		c.Set(ctxUserRole, user.Role)
		c.Next()
	}
}

// rateLimiterStore keeps one token bucket per identity (user_id or IP).
type rateLimiterStore struct {
	mu       sync.Mutex
	limiters map[string]*rate.Limiter
	rps      rate.Limit
	burst    int
}

func newStore(rps float64, burst int) *rateLimiterStore {
	return &rateLimiterStore{
		limiters: make(map[string]*rate.Limiter),
		rps:      rate.Limit(rps),
		burst:    burst,
	}
}

func (s *rateLimiterStore) get(key string) *rate.Limiter {
	s.mu.Lock()
	defer s.mu.Unlock()
	if l, ok := s.limiters[key]; ok {
		return l
	}
	l := rate.NewLimiter(s.rps, s.burst)
	s.limiters[key] = l
	return l
}

// RateLimit enforces a per-identity token bucket.
// Service API-key traffic (eval harness, internal jobs) is exempt.
func RateLimit(rps float64, burst int) gin.HandlerFunc {
	store := newStore(rps, burst)
	return func(c *gin.Context) {
		if c.GetString(ctxUserRole) == "service" {
			c.Next()
			return
		}
		key := c.GetString(ctxUserID)
		if key == "" {
			key = c.ClientIP()
		}
		if !store.get(key).Allow() {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{"error": "rate limit exceeded"})
			return
		}
		c.Next()
	}
}

// RequestIDFrom extracts the request id from context (helper for handlers).
func RequestIDFrom(c *gin.Context) string { return c.GetString(ctxRequestID) }

// UserIDFrom returns the authenticated user id (if any).
func UserIDFrom(c *gin.Context) string { return c.GetString(ctxUserID) }

// UserEmailFrom returns the authenticated user email (if any).
func UserEmailFrom(c *gin.Context) string { return c.GetString(ctxUserEmail) }
