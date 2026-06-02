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
	handler := corsMiddleware(securityMiddleware(mux, ks), ks)

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

		// Token is optional from the browser (the plaintext is only ever delivered
		// to the agent at pairing time — the browser has no way to obtain it).
		// Auth model: if a token is supplied, it MUST match. If not, we fall back
		// to Origin-only check against paired sites — the same intent expressed
		// in e_sign.js getSiteToken().
		token := r.Header.Get("X-DSC-Site-Token")
		if token != "" {
			if !ks.ValidateToken(origin, token) {
				writeError(w, ErrUnauthorized, http.StatusForbidden)
				return
			}
		} else {
			if !ks.IsPairedSite(origin) {
				writeError(w, ErrUnauthorized, http.StatusForbidden)
				return
			}
		}

		next.ServeHTTP(w, r)
	})
}

// corsMiddleware adds CORS headers so the browser can call localhost from the Frappe site.
// Also opts into Chrome's Private Network Access (PNA): when a page on a "less private"
// network (LAN) calls a "more private" endpoint (127.0.0.1), Chrome requires the target
// to explicitly allow the access via Access-Control-Allow-Private-Network.
//
// We do NOT reflect arbitrary Origins. Echoing any incoming Origin into
// Access-Control-Allow-Origin let any website on the internet read the agent's
// responses (cert lists, signing results). Instead we only emit CORS headers
// when the origin is allowed: a site that is already paired, or — for the
// bootstrap endpoints only — the site currently completing the pairing
// handshake (which is independently gated by a one-time code + user
// confirmation in HandlePair).
func corsMiddleware(next http.Handler, ks *Keystore) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if origin != "" && corsOriginAllowed(origin, r.URL.Path, ks) {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Vary", "Origin")
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type, X-DSC-Site-Token")
			w.Header().Set("Access-Control-Max-Age", "3600")

			// Chrome PNA opt-in — required when a page on a LAN/public IP fetches
			// localhost. Only emitted for allowed origins, alongside ACAO.
			if r.Header.Get("Access-Control-Request-Private-Network") == "true" {
				w.Header().Set("Access-Control-Allow-Private-Network", "true")
			}
		}

		// Handle preflight
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}

		next.ServeHTTP(w, r)
	})
}

// corsOriginAllowed decides whether to emit CORS headers for the given origin.
//
// Already-paired sites are always allowed. The bootstrap endpoints /v1/pair and
// /v1/status must also work for a not-yet-paired origin, otherwise the very
// first pairing handshake (and agent auto-detection) could never complete. Those
// two are safe to expose: /v1/status returns only non-sensitive liveness data,
// and /v1/pair requires a valid one-time pairing code plus an explicit user
// confirmation before it stores anything. Every sensitive endpoint (/v1/sign,
// /v1/certs) requires the origin to already be paired.
func corsOriginAllowed(origin, path string, ks *Keystore) bool {
	if ks.IsPairedSite(origin) {
		return true
	}
	switch path {
	case "/v1/pair", "/v1/status":
		return true
	default:
		return false
	}
}
