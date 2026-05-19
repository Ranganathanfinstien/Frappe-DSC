//go:build softhsm
// +build softhsm

// Integration test for the PKCS#11 sign path against a real SoftHSM2 token.
//
// Prerequisites:
//
//	./test_setup.sh   # creates a SoftHSM2 token labeled "TestDSC" with PIN 1234
//
// Run:
//
//	go test -tags softhsm -v ./...
//
// Skipped automatically (via build tag) when SoftHSM2 / its lib is not available,
// so it never breaks the default `go test ./...` invocation.

package main

import (
	"crypto"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"os"
	"testing"
)

const softhsmLib = "/usr/lib/softhsm/libsofthsm2.so"
const softhsmPIN = "1234"

func skipIfNoSoftHSM(t *testing.T) {
	t.Helper()
	if _, err := os.Stat(softhsmLib); err != nil {
		t.Skipf("SoftHSM2 not installed at %s — skipping integration test", softhsmLib)
	}
}

func TestSoftHSM_DetectAndEnumerate(t *testing.T) {
	skipIfNoSoftHSM(t)

	h := NewPKCS11Handler([]string{softhsmLib})
	defer h.Destroy()

	if libs := h.LoadedLibs(); len(libs) == 0 {
		t.Fatal("SoftHSM lib failed to load — did you run test_setup.sh?")
	}

	tokens := h.DetectTokens()
	if len(tokens) == 0 {
		t.Fatal("no tokens detected — did you run test_setup.sh?")
	}
	t.Logf("detected %d token(s): %+v", len(tokens), tokens)

	certs, err := h.EnumerateCerts()
	if err != nil {
		t.Fatalf("EnumerateCerts: %v", err)
	}
	if len(certs) == 0 {
		t.Fatal("no certs found on token")
	}
	t.Logf("found %d cert(s); first CN=%q fp=%s",
		len(certs), certs[0].SubjectCN, certs[0].FingerprintSHA256)
}

func TestSoftHSM_SignAndVerify(t *testing.T) {
	skipIfNoSoftHSM(t)

	h := NewPKCS11Handler([]string{softhsmLib})
	defer h.Destroy()

	certs, err := h.EnumerateCerts()
	if err != nil || len(certs) == 0 {
		t.Fatalf("EnumerateCerts: %v (need at least one cert on token)", err)
	}

	target := certs[0]
	_, ctx, slot, err := h.FindCertByFingerprint(target.FingerprintSHA256)
	if err != nil {
		t.Fatalf("FindCertByFingerprint: %v", err)
	}

	// Hash arbitrary "document" bytes — this is what the Frappe server would compute
	// from the prepared PDF before sending to the agent.
	docBytes := []byte("dsc-bridge integration test payload")
	docHash := sha256.Sum256(docBytes)

	sig, certDER, err := h.SignHash(ctx, slot, target.FingerprintSHA256, docHash[:], softhsmPIN)
	if err != nil {
		t.Fatalf("SignHash: %v", err)
	}
	if len(sig) == 0 {
		t.Fatal("got empty signature")
	}
	if len(certDER) == 0 {
		t.Fatal("got empty cert DER")
	}
	t.Logf("signature: %d bytes, cert DER: %d bytes", len(sig), len(certDER))

	// Verify the signature against the public key extracted from the cert.
	// This is the same check pyHanko does on the server side after injection.
	cert, err := x509.ParseCertificate(certDER)
	if err != nil {
		t.Fatalf("parse signer cert: %v", err)
	}
	rsaPub, ok := cert.PublicKey.(*rsa.PublicKey)
	if !ok {
		t.Fatalf("expected RSA public key, got %T", cert.PublicKey)
	}

	if err := rsa.VerifyPKCS1v15(rsaPub, crypto.SHA256, docHash[:], sig); err != nil {
		t.Fatalf("signature verification failed: %v\nhash: %s", err, hex.EncodeToString(docHash[:]))
	}
	t.Log("signature verified against cert public key")
}

func TestSoftHSM_FindCertByFingerprintNotFound(t *testing.T) {
	skipIfNoSoftHSM(t)

	h := NewPKCS11Handler([]string{softhsmLib})
	defer h.Destroy()

	_, _, _, err := h.FindCertByFingerprint("0000000000000000000000000000000000000000000000000000000000000000")
	if err == nil {
		t.Fatal("expected error for unknown fingerprint, got nil")
	}
}
