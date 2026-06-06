package validation

import (
	"errors"
	"fmt"
	"strings"
)

// Bounds on the optional context map sent on /chat. Keeps requests cheap
// to parse, log, and forward to the Python service.
const (
	MaxContextKeys      = 16
	MaxContextKeyLen    = 64
	MaxContextValueLen  = 1024
	MaxContextStringLen = 1024
)

// CleanContext returns a copy of ctx with values shallow-validated:
//   - at most MaxContextKeys entries
//   - keys [a-z0-9_], 1..MaxContextKeyLen chars
//   - values must be string | bool | number | []string with bounded length
//
// Anything else is rejected with a descriptive error.
func CleanContext(ctx map[string]any) (map[string]any, error) {
	if ctx == nil {
		return nil, nil
	}
	if len(ctx) > MaxContextKeys {
		return nil, fmt.Errorf("context has %d keys; max is %d", len(ctx), MaxContextKeys)
	}
	out := make(map[string]any, len(ctx))
	for k, v := range ctx {
		if !validKey(k) {
			return nil, fmt.Errorf("context key %q is not allowed (use [a-z0-9_], 1..%d chars)", k, MaxContextKeyLen)
		}
		cv, err := validValue(k, v)
		if err != nil {
			return nil, err
		}
		out[k] = cv
	}
	return out, nil
}

func validKey(k string) bool {
	if k == "" || len(k) > MaxContextKeyLen {
		return false
	}
	for _, r := range k {
		switch {
		case r >= 'a' && r <= 'z',
			r >= '0' && r <= '9',
			r == '_':
		default:
			return false
		}
	}
	return true
}

func validValue(key string, v any) (any, error) {
	switch x := v.(type) {
	case nil:
		return nil, nil
	case string:
		if len(x) > MaxContextValueLen {
			return nil, fmt.Errorf("context.%s: string longer than %d chars", key, MaxContextValueLen)
		}
		return strings.TrimSpace(x), nil
	case bool:
		return x, nil
	case float64, float32, int, int32, int64:
		return x, nil
	case []any:
		if len(x) > MaxContextKeys {
			return nil, fmt.Errorf("context.%s: list longer than %d items", key, MaxContextKeys)
		}
		cleaned := make([]any, 0, len(x))
		for i, item := range x {
			s, ok := item.(string)
			if !ok {
				return nil, fmt.Errorf("context.%s[%d]: only string lists are allowed", key, i)
			}
			if len(s) > MaxContextStringLen {
				return nil, fmt.Errorf("context.%s[%d]: string longer than %d chars", key, i, MaxContextStringLen)
			}
			cleaned = append(cleaned, strings.TrimSpace(s))
		}
		return cleaned, nil
	default:
		return nil, errors.New("context values must be string, bool, number, or list of strings")
	}
}
