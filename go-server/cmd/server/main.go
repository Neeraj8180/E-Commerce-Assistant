// Binary server starts the E-Commerce Agent Go API gateway.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin"

	"github.com/Neeraj8180/ecom-agent/go-server/internal/auth"
	"github.com/Neeraj8180/ecom-agent/go-server/internal/client"
	"github.com/Neeraj8180/ecom-agent/go-server/internal/config"
	"github.com/Neeraj8180/ecom-agent/go-server/internal/handlers"
	"github.com/Neeraj8180/ecom-agent/go-server/internal/middleware"
	"github.com/Neeraj8180/ecom-agent/go-server/internal/observability"
	"github.com/Neeraj8180/ecom-agent/go-server/internal/validation"
)

const maxRequestBodyBytes = 64 * 1024

func main() {
	cfg, err := config.Load()
	if err != nil {
		fmt.Fprintf(os.Stderr, "config: %v\n", err)
		os.Exit(1)
	}

	logger := observability.NewLogger(cfg.LogLevel)
	slog.SetDefault(logger)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	shutdownTracer, err := observability.InitTracer(ctx, cfg.OTelServiceName, cfg.OTelEndpoint)
	if err != nil {
		logger.Warn("tracing init failed (continuing without tracing)", slog.String("error", err.Error()))
		shutdownTracer = func(context.Context) error { return nil }
	}
	defer func() {
		shutdownCtx, c := context.WithTimeout(context.Background(), 5*time.Second)
		defer c()
		_ = shutdownTracer(shutdownCtx)
	}()

	// Database pool (required for auth).
	dbPool, err := pgxpool.New(ctx, cfg.DatabaseURL)
	if err != nil {
		logger.Error("database connection failed", slog.String("error", err.Error()))
		os.Exit(1)
	}
	defer dbPool.Close()

	// Verify DB connectivity before serving.
	pingCtx, pingCancel := context.WithTimeout(ctx, 5*time.Second)
	if err := dbPool.Ping(pingCtx); err != nil {
		pingCancel()
		logger.Error("database ping failed", slog.String("error", err.Error()))
		os.Exit(1)
	}
	pingCancel()

	authSvc := auth.NewService(dbPool, cfg.JWTSecret, cfg.JWTIssuer, cfg.JWTTTL)

	metrics := observability.NewMetrics()
	agent := client.NewAgentClient(cfg.PythonAgentURL, cfg.PythonAgentTimeout)
	deps := &handlers.Deps{
		Agent: agent, DB: dbPool, Logger: logger, AgentTimeout: cfg.PythonAgentTimeout,
	}

	if cfg.Environment == "production" {
		gin.SetMode(gin.ReleaseMode)
	}
	if err := validation.Register(); err != nil {
		logger.Error("register validators", slog.String("error", err.Error()))
		os.Exit(1)
	}
	router := gin.New()
	router.Use(gin.Recovery())
	router.Use(otelgin.Middleware(cfg.OTelServiceName))
	router.Use(middleware.RequestID())
	router.Use(middleware.MaxBodyBytes(maxRequestBodyBytes))
	router.Use(middleware.StructuredLogger(logger, metrics, cfg.OTelServiceName))

	// Public endpoints
	router.GET("/health", handlers.Health(deps))
	router.GET("/metrics", gin.WrapH(promhttp.Handler()))
	router.POST("/auth/login", handlers.Login(authSvc, logger))

	// Authenticated + rate-limited API
	api := router.Group("/")
	api.Use(middleware.Auth(authSvc, cfg.APIKey))
	api.Use(middleware.RateLimit(cfg.RateLimitRPS, cfg.RateLimitBurst))
	{
		api.POST("/chat", handlers.Chat(deps))
		api.POST("/replay", handlers.Replay(deps))
	}

	srv := &http.Server{
		Addr:              fmt.Sprintf(":%d", cfg.Port),
		Handler:           router,
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		logger.Info("starting go-server", slog.Int("port", cfg.Port))
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("server error", slog.String("error", err.Error()))
			cancel()
		}
	}()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	select {
	case <-sig:
		logger.Info("shutdown signal received")
	case <-ctx.Done():
	}

	shutdownCtx, c := context.WithTimeout(context.Background(), 10*time.Second)
	defer c()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		logger.Error("graceful shutdown failed", slog.String("error", err.Error()))
	}
	logger.Info("server stopped")
}
