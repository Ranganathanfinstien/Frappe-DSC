package main

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/miekg/pkcs11"
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

// mapPKCS11Error converts a PKCS#11 error into the agent's domain error code
// and the appropriate HTTP status. Falls back to INTERNAL_ERROR / 500.
//
// Reference: PKCS#11 v2.40 §A "Manifest constants" for CKR_* values.
func mapPKCS11Error(err error) (code string, httpStatus int) {
	if err == nil {
		return ErrInternalError, http.StatusInternalServerError
	}

	var p11Err pkcs11.Error
	if !errors.As(err, &p11Err) {
		return ErrInternalError, http.StatusInternalServerError
	}

	switch uint(p11Err) {
	case pkcs11.CKR_PIN_INCORRECT:
		return ErrPINIncorrect, http.StatusUnauthorized
	case pkcs11.CKR_PIN_LOCKED:
		return ErrPINLocked, http.StatusForbidden
	case pkcs11.CKR_PIN_INVALID, pkcs11.CKR_PIN_LEN_RANGE:
		return ErrPINIncorrect, http.StatusUnauthorized
	case pkcs11.CKR_FUNCTION_CANCELED:
		return ErrPINCancelled, http.StatusBadRequest
	case pkcs11.CKR_TOKEN_NOT_PRESENT, pkcs11.CKR_TOKEN_NOT_RECOGNIZED, pkcs11.CKR_DEVICE_REMOVED:
		return ErrTokenNotFound, http.StatusNotFound
	case pkcs11.CKR_MECHANISM_INVALID, pkcs11.CKR_MECHANISM_PARAM_INVALID:
		return ErrUnsupportedAlgo, http.StatusBadRequest
	case pkcs11.CKR_KEY_HANDLE_INVALID, pkcs11.CKR_OBJECT_HANDLE_INVALID:
		return ErrCertNotFound, http.StatusNotFound
	default:
		return ErrInternalError, http.StatusInternalServerError
	}
}
