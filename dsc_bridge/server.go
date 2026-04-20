package main

import (
	"crypto/tls"
	"fmt"
	"log"
	"net/http"
)

// StartServer creates and runs the HTTPS server on 127.0.0.1:4645.
func StartServer(cfg *Config, tlsCert tls.Certificate, agentFP string, pkcs11Handler *PKCS11Handler, ks *Keystore) error {
	handlers := &Handlers{
		pkcs11:  pkcs11Handler,
		ks:      ks,
		agentFP: agentFP,
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/v1/status", handlers.HandleStatus)
	mux.HandleFunc("/v1/certs", handlers.HandleCerts)
	mux.HandleFunc("/v1/pair", handlers.HandlePair)
	mux.HandleFunc("/v1/sign", handlers.HandleSign)

	// Wrap with security middleware
	handler := corsMiddleware(securityMiddleware(mux, ks))

	addr := fmt.Sprintf("%s:%d", cfg.Host, cfg.Port)

	server := &http.Server{
		Addr:    addr,
		Handler: handler,
		TLSConfig: &tls.Config{
			Certificates: []tls.Certificate{tlsCert},
			MinVersion:   tls.VersionTLS12,
		},
	}

	log.Printf("dsc-bridge %s listening on https://%s", AgentVersion, addr)
	return server.ListenAndServeTLS("", "")
}

// securityMiddleware enforces X-DSC-Site-Token and Origin header checks.
// The /v1/pair endpoint is exempt from token checks (it's how pairing starts).
func securityMiddleware(next http.Handler, ks *Keystore) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// /v1/pair is exempt — it's the pairing handshake
		if r.URL.Path == "/v1/pair" {
			next.ServeHTTP(w, r)
			return
		}

		// /v1/status is also accessible without token for agent detection
		if r.URL.Path == "/v1/status" && r.Method == http.MethodGet {
			next.ServeHTTP(w, r)
			return
		}

		// Check Origin header
		origin := r.Header.Get("Origin")
		if origin == "" {
			writeError(w, ErrUnauthorized, http.StatusForbidden)
			return
		}

		// Check X-DSC-Site-Token
		token := r.Header.Get("X-DSC-Site-Token")
		if token == "" {
			writeError(w, ErrUnauthorized, http.StatusForbidden)
			return
		}

		// Validate token against paired site
		if !ks.ValidateToken(origin, token) {
			writeError(w, ErrUnauthorized, http.StatusForbidden)
			return
		}

		next.ServeHTTP(w, r)
	})
}

// corsMiddleware adds CORS headers so the browser can call localhost from the Frappe site.
func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if origin != "" {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type, X-DSC-Site-Token")
			w.Header().Set("Access-Control-Max-Age", "3600")
		}

		// Handle preflight
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}

		next.ServeHTTP(w, r)
	})
}
