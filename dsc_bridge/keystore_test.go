package main

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/zalando/go-keyring"
)

func newTestKeystore(t *testing.T) *Keystore {
	t.Helper()
	keyring.MockInit()
	dir := t.TempDir()
	ks, err := NewKeystore(filepath.Join(dir, "paired_sites.json"))
	if err != nil {
		t.Fatalf("NewKeystore: %v", err)
	}
	return ks
}

func TestKeystoreAddTokenInKeychainNotFile(t *testing.T) {
	ks := newTestKeystore(t)

	site := PairedSite{
		SiteURL:           "https://erp.example.com",
		SiteToken:         "super-secret-token",
		PairedOn:          "2026-04-20T10:00:00Z",
		AgentRegistration: "DSC-AGT-00001",
	}

	if err := ks.AddSite(site); err != nil {
		t.Fatalf("AddSite: %v", err)
	}

	// File on disk MUST NOT contain the secret token
	data, err := os.ReadFile(ks.filePath)
	if err != nil {
		t.Fatalf("read keystore file: %v", err)
	}
	if contains(data, "super-secret-token") {
		t.Fatal("plaintext site token leaked into keystore JSON file")
	}

	// Token round-trips via the keychain
	got, err := ks.Token(site.SiteURL)
	if err != nil {
		t.Fatalf("Token: %v", err)
	}
	if got != site.SiteToken {
		t.Errorf("got token %q, want %q", got, site.SiteToken)
	}
}

func TestKeystoreValidateToken(t *testing.T) {
	ks := newTestKeystore(t)

	if err := ks.AddSite(PairedSite{
		SiteURL:   "https://erp.example.com",
		SiteToken: "correct-horse-battery-staple",
		PairedOn:  "2026-04-20T10:00:00Z",
	}); err != nil {
		t.Fatalf("AddSite: %v", err)
	}

	if !ks.ValidateToken("https://erp.example.com", "correct-horse-battery-staple") {
		t.Error("ValidateToken returned false for the correct token")
	}
	if ks.ValidateToken("https://erp.example.com", "wrong-token") {
		t.Error("ValidateToken returned true for the wrong token")
	}
	if ks.ValidateToken("https://other.example.com", "any-token") {
		t.Error("ValidateToken returned true for an unpaired site")
	}
}

func TestKeystoreRemoveSite(t *testing.T) {
	ks := newTestKeystore(t)

	site := PairedSite{
		SiteURL:   "https://erp.example.com",
		SiteToken: "secret",
		PairedOn:  "2026-04-20T10:00:00Z",
	}
	if err := ks.AddSite(site); err != nil {
		t.Fatalf("AddSite: %v", err)
	}

	if err := ks.RemoveSite(site.SiteURL); err != nil {
		t.Fatalf("RemoveSite: %v", err)
	}

	if _, ok := ks.GetSite(site.SiteURL); ok {
		t.Error("site still present after RemoveSite")
	}
	if _, err := ks.Token(site.SiteURL); err == nil {
		t.Error("Token returned no error after RemoveSite — keychain entry leaked")
	}
}

func TestKeystorePersistsAcrossLoad(t *testing.T) {
	keyring.MockInit()
	dir := t.TempDir()
	path := filepath.Join(dir, "paired_sites.json")

	ks1, err := NewKeystore(path)
	if err != nil {
		t.Fatalf("NewKeystore: %v", err)
	}
	if err := ks1.AddSite(PairedSite{
		SiteURL:   "https://erp.example.com",
		SiteToken: "persisted-token",
		PairedOn:  "2026-04-20T10:00:00Z",
	}); err != nil {
		t.Fatalf("AddSite: %v", err)
	}

	ks2, err := NewKeystore(path)
	if err != nil {
		t.Fatalf("re-load NewKeystore: %v", err)
	}

	urls := ks2.ListSiteURLs()
	if len(urls) != 1 || urls[0] != "https://erp.example.com" {
		t.Errorf("expected one site after reload, got %v", urls)
	}

	if !ks2.ValidateToken("https://erp.example.com", "persisted-token") {
		t.Error("token did not survive Keystore reload")
	}
}

func contains(data []byte, needle string) bool {
	return len(data) > 0 && stringInBytes(data, needle)
}

func stringInBytes(haystack []byte, needle string) bool {
	if needle == "" {
		return true
	}
	n := len(needle)
	for i := 0; i+n <= len(haystack); i++ {
		if string(haystack[i:i+n]) == needle {
			return true
		}
	}
	return false
}
