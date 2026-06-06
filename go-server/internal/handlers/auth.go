package handlers

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/Neeraj8180/ecom-agent/go-server/internal/auth"
	"github.com/Neeraj8180/ecom-agent/go-server/internal/middleware"
	"github.com/Neeraj8180/ecom-agent/go-server/internal/models"
)

// Login handles POST /auth/login.
func Login(svc *auth.Service, logger *slog.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		rid := middleware.RequestIDFrom(c)
		var req models.LoginRequest
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, models.ErrorResponse{
				Error: "invalid request", Detail: humanizeBindErr(err), RequestID: rid,
			})
			return
		}
		ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
		defer cancel()
		user, token, err := svc.Login(ctx, req.Email, req.Password)
		if err != nil {
			if errors.Is(err, auth.ErrInvalidCredentials) {
				c.JSON(http.StatusUnauthorized, models.ErrorResponse{Error: "invalid credentials", RequestID: rid})
				return
			}
			logger.ErrorContext(ctx, "login error",
				slog.String("request_id", rid),
				slog.String("email", req.Email),
				slog.String("error", err.Error()),
			)
			c.JSON(http.StatusInternalServerError, models.ErrorResponse{Error: "login failed", RequestID: rid})
			return
		}
		c.JSON(http.StatusOK, models.LoginResponse{
			AccessToken: token,
			TokenType:   "Bearer",
			ExpiresIn:   int64(time.Hour.Seconds()),
			User:        *user,
		})
	}
}
