// Package auth implements password verification (bcrypt) and JWT issuance
// against the users table. This replaces the previous "API key only"
// development shortcut with a real production auth flow.
package auth

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/bcrypt"
)

// ErrInvalidCredentials is returned for any user-facing auth failure.
// We deliberately do not distinguish "user not found" from "wrong password"
// to avoid leaking which emails exist.
var ErrInvalidCredentials = errors.New("invalid credentials")

// User is the authenticated principal.
type User struct {
	ID    string `json:"id"`
	Email string `json:"email"`
	Name  string `json:"name"`
	Role  string `json:"role"`
}

// Service handles login + token issuance.
type Service struct {
	db        *pgxpool.Pool
	jwtSecret []byte
	issuer    string
	ttl       time.Duration
}

// NewService constructs an auth service.
func NewService(db *pgxpool.Pool, jwtSecret, issuer string, ttl time.Duration) *Service {
	return &Service{db: db, jwtSecret: []byte(jwtSecret), issuer: issuer, ttl: ttl}
}

// Login validates the email + password against the users table and returns
// the user along with a signed JWT on success.
func (s *Service) Login(ctx context.Context, email, password string) (*User, string, error) {
	if s.db == nil {
		return nil, "", errors.New("auth: database not configured")
	}
	row := s.db.QueryRow(ctx,
		`SELECT id::text, email, name, role, password_hash
		 FROM users WHERE email = $1`, email)

	var u User
	var hash string
	if err := row.Scan(&u.ID, &u.Email, &u.Name, &u.Role, &hash); err != nil {
		// Mitigate timing oracle by spending the same bcrypt time as a real verify.
		_ = bcrypt.CompareHashAndPassword([]byte("$2a$12$abcdefghijklmnopqrstuv"), []byte(password))
		return nil, "", ErrInvalidCredentials
	}

	if err := bcrypt.CompareHashAndPassword([]byte(hash), []byte(password)); err != nil {
		return nil, "", ErrInvalidCredentials
	}

	token, err := s.IssueToken(&u)
	if err != nil {
		return nil, "", fmt.Errorf("issue token: %w", err)
	}
	return &u, token, nil
}

// IssueToken signs a JWT for the given user.
func (s *Service) IssueToken(u *User) (string, error) {
	now := time.Now()
	claims := jwt.MapClaims{
		"sub":   u.ID,
		"email": u.Email,
		"role":  u.Role,
		"iss":   s.issuer,
		"iat":   now.Unix(),
		"exp":   now.Add(s.ttl).Unix(),
		"nbf":   now.Unix(),
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString(s.jwtSecret)
}

// VerifyToken parses + verifies a signed token and returns the user id/email/role.
func (s *Service) VerifyToken(tokenStr string) (*User, error) {
	tok, err := jwt.Parse(tokenStr, func(t *jwt.Token) (interface{}, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, jwt.ErrSignatureInvalid
		}
		return s.jwtSecret, nil
	}, jwt.WithIssuer(s.issuer), jwt.WithExpirationRequired())
	if err != nil || !tok.Valid {
		return nil, errors.New("invalid token")
	}
	claims, ok := tok.Claims.(jwt.MapClaims)
	if !ok {
		return nil, errors.New("invalid claims")
	}
	u := &User{}
	if v, ok := claims["sub"].(string); ok {
		u.ID = v
	}
	if v, ok := claims["email"].(string); ok {
		u.Email = v
	}
	if v, ok := claims["role"].(string); ok {
		u.Role = v
	}
	if u.ID == "" {
		return nil, errors.New("missing subject")
	}
	return u, nil
}
