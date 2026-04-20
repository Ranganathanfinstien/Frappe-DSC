package main

import (
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"runtime"
	"time"
)

// Handlers holds dependencies for HTTP handlers.
type Handlers struct {
	pkcs11  *PKCS11Handler
	ks      *Keystore
	agentFP string
}

// --- GET /v1/status ---

type StatusResponse struct {
	AgentVersion   string      `json:"agent_version"`
	Platform       string      `json:"platform"`
	PairedSites    []string    `json:"paired_sites"`
	TokensDetected []TokenInfo `json:"tokens_detected"`
	PKCS11Libs     []string    `json:"pkcs11_libs_loaded"`
}

func (h *Handlers) HandleStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	resp := StatusResponse{
		AgentVersion:   AgentVersion,
		Platform:       runtime.GOOS,
		PairedSites:    h.ks.ListSiteURLs(),
		TokensDetected: h.pkcs11.DetectTokens(),
		PKCS11Libs:     h.pkcs11.LoadedLibs(),
	}

	// Ensure non-nil slices for JSON
	if resp.PairedSites == nil {
		resp.PairedSites = []string{}
	}
	if resp.TokensDetected == nil {
		resp.TokensDetected = []TokenInfo{}
	}
	if resp.PKCS11Libs == nil {
		resp.PKCS11Libs = []string{}
	}

	writeJSON(w, http.StatusOK, resp)
}

// --- GET /v1/certs ---

type CertsResponse struct {
	Certs []CertInfo `json:"certs"`
}

func (h *Handlers) HandleCerts(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	certs, err := h.pkcs11.EnumerateCerts()
	if err != nil {
		writeErrorMsg(w, ErrInternalError, err.Error(), http.StatusInternalServerError)
		return
	}

	if certs == nil {
		certs = []CertInfo{}
	}

	writeJSON(w, http.StatusOK, CertsResponse{Certs: certs})
}

// --- POST /v1/pair ---

type PairRequest struct {
	PairingCode string `json:"pairing_code"`
	SiteURL     string `json:"site_url"`
}

type PairResponse struct {
	AgentFingerprint string `json:"agent_fingerprint"`
	AgentVersion     string `json:"agent_version"`
}

func (h *Handlers) HandlePair(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req PairRequest
	if err := readJSON(r, &req); err != nil {
		writeErrorMsg(w, ErrInternalError, "invalid request body", http.StatusBadRequest)
		return
	}

	if req.PairingCode == "" || req.SiteURL == "" {
		writeErrorMsg(w, ErrInternalError, "pairing_code and site_url are required", http.StatusBadRequest)
		return
	}

	// Validate pairing code against the Frappe site
	pairing, err := validatePairingCode(req.SiteURL, req.PairingCode, h.agentFP)
	if err != nil {
		writeError(w, ErrInvalidPairingCode, http.StatusForbidden)
		return
	}

	// Store the paired site (token goes to OS keychain, metadata to JSON)
	err = h.ks.AddSite(PairedSite{
		SiteURL:           req.SiteURL,
		SiteToken:         pairing.SiteToken,
		PairedOn:          time.Now().UTC().Format(time.RFC3339),
		AgentRegistration: pairing.AgentRegistration,
	})
	if err != nil {
		writeErrorMsg(w, ErrInternalError, "failed to store pairing", http.StatusInternalServerError)
		return
	}

	writeJSON(w, http.StatusOK, PairResponse{
		AgentFingerprint: h.agentFP,
		AgentVersion:     AgentVersion,
	})
}

// pairingResult holds what the Frappe server returns from validate_pairing_code.
type pairingResult struct {
	SiteToken         string
	AgentRegistration string
}

// validatePairingCode calls the Frappe site to validate the one-time pairing code.
// Returns the long-lived site token + agent registration ID on success.
//
// We marshal the request body via encoding/json (not fmt.Sprintf) so that
// pairing codes containing JSON-special characters can't break out of the body.
func validatePairingCode(siteURL, code, agentFP string) (*pairingResult, error) {
	url := fmt.Sprintf("%s/api/method/e_sign.api.agent.validate_pairing_code", siteURL)

	reqBody, err := json.Marshal(map[string]string{
		"pairing_code":      code,
		"agent_fingerprint": agentFP,
	})
	if err != nil {
		return nil, fmt.Errorf("marshalling request: %w", err)
	}

	resp, err := http.Post(url, "application/json", bytesReader(reqBody))
	if err != nil {
		return nil, fmt.Errorf("contacting site: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("site returned status %d", resp.StatusCode)
	}

	var result struct {
		Message struct {
			SiteToken         string `json:"site_token"`
			AgentRegistration string `json:"agent_registration"`
		} `json:"message"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, err
	}

	if result.Message.SiteToken == "" {
		return nil, fmt.Errorf("no site_token in response")
	}

	return &pairingResult{
		SiteToken:         result.Message.SiteToken,
		AgentRegistration: result.Message.AgentRegistration,
	}, nil
}

// --- POST /v1/sign ---

type SignRequest struct {
	SessionID           string `json:"session_id"`
	HashToSign          string `json:"hash_to_sign"`
	HashAlgorithm       string `json:"hash_algorithm"`
	ExpectedFingerprint string `json:"expected_fingerprint"`
}

type SignResponse struct {
	SessionID        string   `json:"session_id"`
	SignatureBytesB64 string  `json:"signature_bytes_b64"`
	CertDERB64       string   `json:"cert_der_b64"`
	CertChainDERB64  []string `json:"cert_chain_der_b64"`
	OCSPDERB64       string   `json:"ocsp_der_b64"`
	SignedAtUTC      string   `json:"signed_at_utc"`
	AgentFingerprint string   `json:"agent_fingerprint"`
}

func (h *Handlers) HandleSign(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req SignRequest
	if err := readJSON(r, &req); err != nil {
		writeErrorMsg(w, ErrInternalError, "invalid request body", http.StatusBadRequest)
		return
	}

	if req.HashAlgorithm != "" && req.HashAlgorithm != "sha256" {
		writeError(w, ErrUnsupportedAlgo, http.StatusBadRequest)
		return
	}

	// Find the certificate across all tokens
	certInfo, ctx, slot, err := h.pkcs11.FindCertByFingerprint(req.ExpectedFingerprint)
	if err != nil {
		tokens := h.pkcs11.DetectTokens()
		if len(tokens) == 0 {
			writeError(w, ErrTokenNotFound, http.StatusNotFound)
		} else {
			writeError(w, ErrCertNotFound, http.StatusNotFound)
		}
		return
	}
	_ = certInfo

	// Decode the hex hash
	hashBytes, err := hex.DecodeString(req.HashToSign)
	if err != nil {
		writeErrorMsg(w, ErrInternalError, "invalid hash_to_sign hex", http.StatusBadRequest)
		return
	}

	// Sign the hash — this triggers PIN dialog via C_Login
	// For tokens with native PIN dialog, pass empty string.
	// The token vendor's middleware handles PIN capture.
	sigBytes, certDER, err := h.pkcs11.SignHash(ctx, slot, req.ExpectedFingerprint, hashBytes, "")
	if err != nil {
		code, status := mapPKCS11Error(err)
		writeErrorMsg(w, code, err.Error(), status)
		return
	}

	// Fetch certificate chain via AIA extension
	chainDER, _ := FetchCertChain(certDER)
	certChain := EncodeCertChainB64(chainDER)

	// Fetch OCSP response from cert's AIA OCSP URL
	ocspB64 := ""
	if len(chainDER) > 0 {
		ocspBytes, err := FetchOCSP(certDER, chainDER[0])
		if err != nil {
			log.Printf("OCSP fetch failed (non-fatal): %v", err)
		} else {
			ocspB64 = base64.StdEncoding.EncodeToString(ocspBytes)
		}
	}

	writeJSON(w, http.StatusOK, SignResponse{
		SessionID:         req.SessionID,
		SignatureBytesB64: base64.StdEncoding.EncodeToString(sigBytes),
		CertDERB64:        base64.StdEncoding.EncodeToString(certDER),
		CertChainDERB64:   certChain,
		OCSPDERB64:        ocspB64,
		SignedAtUTC:       time.Now().UTC().Format("2006-01-02T15:04:05Z"),
		AgentFingerprint:  h.agentFP,
	})
}

// --- Helpers ---

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func readJSON(r *http.Request, v interface{}) error {
	defer r.Body.Close()
	return json.NewDecoder(r.Body).Decode(v)
}

