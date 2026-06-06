package validation

import (
	"regexp"
	"strings"
	"unicode"

	"github.com/gin-gonic/gin/binding"
	"github.com/go-playground/validator/v10"
)

var (
	orderIDRe = regexp.MustCompile(`^ORD-[0-9]{3,12}$`)
	skuRe     = regexp.MustCompile(`^[A-Z0-9][A-Z0-9_-]{1,63}$`)
	sessionRe = regexp.MustCompile(`^[A-Za-z0-9_-]{1,128}$`)
)

// Register attaches the project's custom validators to Gin's binding engine.
// Safe to call multiple times — each tag is registered idempotently.
func Register() error {
	v, ok := binding.Validator.Engine().(*validator.Validate)
	if !ok {
		return nil
	}
	if err := v.RegisterValidation("orderid", validateOrderID); err != nil {
		return err
	}
	if err := v.RegisterValidation("sku", validateSKU); err != nil {
		return err
	}
	if err := v.RegisterValidation("session", validateSession); err != nil {
		return err
	}
	return v.RegisterValidation("safetext", validateSafeText)
}

func validateOrderID(fl validator.FieldLevel) bool {
	s := strings.TrimSpace(fl.Field().String())
	if s == "" {
		return true
	}
	return orderIDRe.MatchString(s)
}

func validateSKU(fl validator.FieldLevel) bool {
	s := strings.TrimSpace(fl.Field().String())
	if s == "" {
		return true
	}
	return skuRe.MatchString(s)
}

func validateSession(fl validator.FieldLevel) bool {
	s := strings.TrimSpace(fl.Field().String())
	if s == "" {
		return true
	}
	return sessionRe.MatchString(s)
}

// validateSafeText rejects control characters (except tab and newline) which
// are a common vector for log injection and prompt-injection escapes.
func validateSafeText(fl validator.FieldLevel) bool {
	s := fl.Field().String()
	for _, r := range s {
		if r == '\t' || r == '\n' || r == '\r' {
			continue
		}
		if unicode.IsControl(r) {
			return false
		}
	}
	return true
}
