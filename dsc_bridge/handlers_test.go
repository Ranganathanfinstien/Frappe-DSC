package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestHandleStatus(t *testing.T) {
	ks, _ := NewKeystore("/tmp/dsc-bridge-test-ks.json")
	p := NewPKCS11Handler(nil) // no libs loaded

	h := &Handlers{
		pkcs11:  p,
		ks:      ks,
		agentFP: "test-fingerprint-abc123",
	}

	req := httptest.NewRequest(http.MethodGet, "/v1/status", nil)
	w := httptest.NewRecorder()

	h.HandleStatus(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var resp StatusResponse
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("invalid JSON response: %v", err)
	}

	if resp.AgentVersion != AgentVersion {
		t.Errorf("expected version %s, got %s", AgentVersion, resp.AgentVersion)
	}

	if resp.Platform == "" {
		t.Error("platform should not be empty")
	}

	if resp.PairedSites == nil {
		t.Error("paired_sites should be non-nil empty slice")
	}

	if resp.TokensDetected == nil {
		t.Error("tokens_detected should be non-nil empty slice")
	}

	if resp.PKCS11Libs == nil {
		t.Error("pkcs11_libs_loaded should be non-nil empty slice")
	}
}

func TestHandleStatusMethodNotAllowed(t *testing.T) {
	ks, _ := NewKeystore("/tmp/dsc-bridge-test-ks.json")
	p := NewPKCS11Handler(nil)

	h := &Handlers{pkcs11: p, ks: ks, agentFP: "test"}

	req := httptest.NewRequest(http.MethodPost, "/v1/status", nil)
	w := httptest.NewRecorder()

	h.HandleStatus(w, req)

	if w.Code != http.StatusMethodNotAllowed {
		t.Fatalf("expected 405, got %d", w.Code)
	}
}

func TestHandleCertsNoTokens(t *testing.T) {
	ks, _ := NewKeystore("/tmp/dsc-bridge-test-ks.json")
	p := NewPKCS11Handler(nil)

	h := &Handlers{pkcs11: p, ks: ks, agentFP: "test"}

	req := httptest.NewRequest(http.MethodGet, "/v1/certs", nil)
	w := httptest.NewRecorder()

	h.HandleCerts(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var resp CertsResponse
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("invalid JSON: %v", err)
	}

	if len(resp.Certs) != 0 {
		t.Errorf("expected 0 certs, got %d", len(resp.Certs))
	}
}

func TestHandlePairMissingFields(t *testing.T) {
	ks, _ := NewKeystore("/tmp/dsc-bridge-test-ks.json")
	p := NewPKCS11Handler(nil)

	h := &Handlers{pkcs11: p, ks: ks, agentFP: "test"}

	body := `{"pairing_code": "", "site_url": ""}`
	req := httptest.NewRequest(http.MethodPost, "/v1/pair", strings.NewReader(body))
	w := httptest.NewRecorder()

	h.HandlePair(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}
}

func TestHandleSignUnsupportedAlgo(t *testing.T) {
	ks, _ := NewKeystore("/tmp/dsc-bridge-test-ks.json")
	p := NewPKCS11Handler(nil)

	h := &Handlers{pkcs11: p, ks: ks, agentFP: "test"}

	body := `{"session_id": "123", "hash_to_sign": "abc", "hash_algorithm": "md5", "expected_fingerprint": "xyz"}`
	req := httptest.NewRequest(http.MethodPost, "/v1/sign", strings.NewReader(body))
	w := httptest.NewRecorder()

	h.HandleSign(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", w.Code)
	}

	var resp ErrorResponse
	json.Unmarshal(w.Body.Bytes(), &resp)
	if resp.Error != ErrUnsupportedAlgo {
		t.Errorf("expected error %s, got %s", ErrUnsupportedAlgo, resp.Error)
	}
}

func TestHandleSignNoToken(t *testing.T) {
	ks, _ := NewKeystore("/tmp/dsc-bridge-test-ks.json")
	p := NewPKCS11Handler(nil) // no libs = no tokens

	h := &Handlers{pkcs11: p, ks: ks, agentFP: "test"}

	body := `{"session_id": "123", "hash_to_sign": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890", "hash_algorithm": "sha256", "expected_fingerprint": "xyz"}`
	req := httptest.NewRequest(http.MethodPost, "/v1/sign", strings.NewReader(body))
	w := httptest.NewRecorder()

	h.HandleSign(w, req)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", w.Code)
	}

	var resp ErrorResponse
	json.Unmarshal(w.Body.Bytes(), &resp)
	if resp.Error != ErrTokenNotFound {
		t.Errorf("expected error %s, got %s", ErrTokenNotFound, resp.Error)
	}
}

func TestSecurityMiddlewareBlocksNoToken(t *testing.T) {
	ks, _ := NewKeystore("/tmp/dsc-bridge-test-ks.json")

	inner := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	handler := securityMiddleware(inner, ks)

	// Request to /v1/certs without headers should be blocked
	req := httptest.NewRequest(http.MethodGet, "/v1/certs", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d", w.Code)
	}
}

func TestSecurityMiddlewareAllowsStatus(t *testing.T) {
	ks, _ := NewKeystore("/tmp/dsc-bridge-test-ks.json")

	inner := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	handler := securityMiddleware(inner, ks)

	// GET /v1/status should be allowed without auth
	req := httptest.NewRequest(http.MethodGet, "/v1/status", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
}

func TestSecurityMiddlewareAllowsPair(t *testing.T) {
	ks, _ := NewKeystore("/tmp/dsc-bridge-test-ks.json")

	inner := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})

	handler := securityMiddleware(inner, ks)

	// POST /v1/pair should be allowed without auth
	req := httptest.NewRequest(http.MethodPost, "/v1/pair", nil)
	w := httptest.NewRecorder()

	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}
}

func TestErrorResponse(t *testing.T) {
	w := httptest.NewRecorder()
	writeError(w, ErrTokenNotFound, http.StatusNotFound)

	var resp ErrorResponse
	json.Unmarshal(w.Body.Bytes(), &resp)

	if resp.Error != ErrTokenNotFound {
		t.Errorf("expected %s, got %s", ErrTokenNotFound, resp.Error)
	}
	if !resp.Recoverable {
		t.Error("TOKEN_NOT_FOUND should be recoverable")
	}
	if resp.Message == "" {
		t.Error("message should not be empty")
	}
}
