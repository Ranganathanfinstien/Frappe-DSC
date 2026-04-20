package main

import (
	"encoding/json"
	"net/http"
)

// Error codes returned by the agent.
const (
	ErrTokenNotFound      = "TOKEN_NOT_FOUND"
	ErrCertNotFound       = "CERT_NOT_FOUND"
	ErrCertMismatch       = "CERT_MISMATCH"
	ErrPINCancelled       = "PIN_CANCELLED"
	ErrPINIncorrect       = "PIN_INCORRECT"
	ErrPINLocked          = "PIN_LOCKED"
	ErrOCSPUnavailable    = "OCSP_UNAVAILABLE"
	ErrUnsupportedAlgo    = "UNSUPPORTED_ALGORITHM"
	ErrInternalError      = "INTERNAL_ERROR"
	ErrUnauthorized       = "UNAUTHORIZED"
	ErrInvalidPairingCode = "INVALID_PAIRING_CODE"
)

// ErrorResponse is the standard error JSON envelope.
type ErrorResponse struct {
	Error       string `json:"error"`
	Message     string `json:"message"`
	Recoverable bool   `json:"recoverable"`
}

// errorMessages maps error codes to human-readable messages.
var errorMessages = map[string]string{
	ErrTokenNotFound:      "No USB token detected",
	ErrCertNotFound:       "No certificate found on token",
	ErrCertMismatch:       "Certificate does not match the expected fingerprint",
	ErrPINCancelled:       "PIN entry was cancelled",
	ErrPINIncorrect:       "Incorrect PIN entered",
	ErrPINLocked:          "Token PIN is locked — contact your token administrator",
	ErrOCSPUnavailable:    "OCSP responder is unreachable — signing succeeded but revocation check failed",
	ErrUnsupportedAlgo:    "The requested signing algorithm is not supported by this token",
	ErrInternalError:      "An unexpected error occurred in the agent",
	ErrUnauthorized:       "Request is not authorized — missing or invalid site token",
	ErrInvalidPairingCode: "Pairing code is invalid or has expired",
}

// recoverableErrors are errors where the user can retry.
var recoverableErrors = map[string]bool{
	ErrTokenNotFound:   true,
	ErrCertNotFound:    true,
	ErrPINCancelled:    true,
	ErrPINIncorrect:    true,
	ErrOCSPUnavailable: true,
}

// writeError sends a JSON error response.
func writeError(w http.ResponseWriter, code string, httpStatus int) {
	msg, ok := errorMessages[code]
	if !ok {
		msg = "Unknown error"
	}

	resp := ErrorResponse{
		Error:       code,
		Message:     msg,
		Recoverable: recoverableErrors[code],
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(httpStatus)
	json.NewEncoder(w).Encode(resp)
}

// writeErrorMsg sends a JSON error response with a custom message.
func writeErrorMsg(w http.ResponseWriter, code string, msg string, httpStatus int) {
	resp := ErrorResponse{
		Error:       code,
		Message:     msg,
		Recoverable: recoverableErrors[code],
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(httpStatus)
	json.NewEncoder(w).Encode(resp)
}
