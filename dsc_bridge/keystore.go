package main

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"sync"

	"github.com/zalando/go-keyring"
)

// keyringService is the service name used to store site tokens in the OS
// keychain (Windows Credential Manager / macOS Keychain / Linux libsecret).
const keyringService = "dsc-bridge"

// PairedSite represents a Frappe site that this agent is paired with.
//
// SiteToken is populated only transiently — when reading from disk, the token
// is fetched from the OS keychain on demand via Keystore.Token(), so it never
// rests in the JSON metadata file.
type PairedSite struct {
	SiteURL          string `json:"site_url"`
	SiteToken        string `json:"-"` // never serialised
	PairedOn         string `json:"paired_on"`
	AgentRegistration string `json:"agent_registration,omitempty"`
}

// Keystore manages paired sites.
//
// Non-secret metadata (site URL, pairing time, server-side registration ID)
// lives in a JSON file under the agent data dir. Secrets (the long-lived
// site token) live in the OS keychain, keyed by the site URL. This means an
// attacker with read access to the data dir cannot forge requests to the
// agent — they would also need to extract the token from the OS keychain.
type Keystore struct {
	mu       sync.RWMutex
	filePath string
	sites    map[string]PairedSite // keyed by site_url
}

// NewKeystore loads or creates the paired sites store.
func NewKeystore(filePath string) (*Keystore, error) {
	ks := &Keystore{
		filePath: filePath,
		sites:    make(map[string]PairedSite),
	}

	data, err := os.ReadFile(filePath)
	if err != nil {
		if os.IsNotExist(err) {
			return ks, nil
		}
		return nil, fmt.Errorf("reading keystore: %w", err)
	}

	if err := json.Unmarshal(data, &ks.sites); err != nil {
		return nil, fmt.Errorf("parsing keystore: %w", err)
	}

	return ks, nil
}

// AddSite stores a new paired site. The plaintext SiteToken is written to the
// OS keychain; only metadata is written to the JSON index.
func (ks *Keystore) AddSite(site PairedSite) error {
	ks.mu.Lock()
	defer ks.mu.Unlock()

	if site.SiteToken != "" {
		if err := keyring.Set(keyringService, site.SiteURL, site.SiteToken); err != nil {
			return fmt.Errorf("storing token in keychain: %w", err)
		}
	}

	// Strip the token before persisting to the metadata file
	stored := site
	stored.SiteToken = ""
	ks.sites[site.SiteURL] = stored
	return ks.save()
}

// GetSite returns metadata for a paired site by URL. The returned PairedSite
// does NOT contain the SiteToken; call Token() to fetch the secret.
func (ks *Keystore) GetSite(siteURL string) (PairedSite, bool) {
	ks.mu.RLock()
	defer ks.mu.RUnlock()

	site, ok := ks.sites[siteURL]
	return site, ok
}

// Token fetches the site token from the OS keychain for the given site URL.
func (ks *Keystore) Token(siteURL string) (string, error) {
	ks.mu.RLock()
	_, ok := ks.sites[siteURL]
	ks.mu.RUnlock()
	if !ok {
		return "", fmt.Errorf("site %s is not paired", siteURL)
	}

	tok, err := keyring.Get(keyringService, siteURL)
	if err != nil {
		if errors.Is(err, keyring.ErrNotFound) {
			return "", fmt.Errorf("keychain entry missing for %s — agent must re-pair", siteURL)
		}
		return "", err
	}
	return tok, nil
}

// ValidateToken checks if the given token matches the stored token for the site,
// using a constant-time comparison to avoid leaking length/prefix via timing.
func (ks *Keystore) ValidateToken(siteURL, token string) bool {
	stored, err := ks.Token(siteURL)
	if err != nil {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(stored), []byte(token)) == 1
}

// ListSiteURLs returns all paired site URLs.
func (ks *Keystore) ListSiteURLs() []string {
	ks.mu.RLock()
	defer ks.mu.RUnlock()

	urls := make([]string, 0, len(ks.sites))
	for url := range ks.sites {
		urls = append(urls, url)
	}
	return urls
}

// RemoveSite removes a paired site from both the metadata index and the OS keychain.
func (ks *Keystore) RemoveSite(siteURL string) error {
	ks.mu.Lock()
	defer ks.mu.Unlock()

	delete(ks.sites, siteURL)

	// Best-effort delete from keychain — don't fail if the entry is already gone
	if err := keyring.Delete(keyringService, siteURL); err != nil && !errors.Is(err, keyring.ErrNotFound) {
		return fmt.Errorf("removing keychain entry: %w", err)
	}

	return ks.save()
}

func (ks *Keystore) save() error {
	data, err := json.MarshalIndent(ks.sites, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(ks.filePath, data, 0600)
}
