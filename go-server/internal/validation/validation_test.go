package validation

import (
	"testing"

	"github.com/gin-gonic/gin/binding"
	"github.com/go-playground/validator/v10"
)

func TestRegister(t *testing.T) {
	if err := Register(); err != nil {
		t.Fatalf("Register: %v", err)
	}
	v, ok := binding.Validator.Engine().(*validator.Validate)
	if !ok {
		t.Fatal("could not get underlying validator engine")
	}

	type chat struct {
		OrderID string `binding:"omitempty,orderid"`
		SKU     string `binding:"omitempty,sku"`
		Sess    string `binding:"omitempty,session"`
		Msg     string `binding:"safetext"`
	}

	good := chat{OrderID: "ORD-1001", SKU: "TSHIRT-BLU-M", Sess: "abc-123", Msg: "hello world\n"}
	if err := v.Struct(good); err != nil {
		t.Fatalf("expected good to pass: %v", err)
	}

	cases := []struct {
		name string
		val  chat
	}{
		{"bad order", chat{OrderID: "BAD-1"}},
		{"bad sku", chat{SKU: "lowercase"}},
		{"bad session", chat{Sess: "has space"}},
		{"control char", chat{Msg: "hi\x00there"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if err := v.Struct(tc.val); err == nil {
				t.Fatalf("expected error for %s", tc.name)
			}
		})
	}
}
