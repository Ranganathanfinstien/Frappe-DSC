package main

import (
	"encoding/json"
	"fmt"
	"os"
	"sync"
)

// PairedSite represents a Frappe site that this agent is paired with.
type PairedSite struct {
	SiteURL   string `json:"site_url"`
	SiteToken string `json:"site_token"`
	PairedOn  string `json:"paired_on"`
}

// Keystore manages paired sites. Stored as a JSON file on disk.
// In production, this should use the OS keystore (Windows Credential Manager,
// macOS Keychain, Linux libsecret). For MVP, we use an encrypted JSON file.
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

// AddSite stores a new paired site.
func (ks *Keystore) AddSite(site PairedSite) error {
	ks.mu.Lock()
	defer ks.mu.Unlock()

	ks.sites[site.SiteURL] = site
	return ks.save()
}

// GetSite returns a paired site by URL.
func (ks *Keystore) GetSite(siteURL string) (PairedSite, bool) {
	ks.mu.RLock()
	defer ks.mu.RUnlock()

	site, ok := ks.sites[siteURL]
	return site, ok
}

// ValidateToken checks if the given token matches the stored token for the site.
func (ks *Keystore) ValidateToken(siteURL, token string) bool {
	site, ok := ks.GetSite(siteURL)
	if !ok {
		return false
	}
	return site.SiteToken == token
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

// RemoveSite removes a paired site.
func (ks *Keystore) RemoveSite(siteURL string) error {
	ks.mu.Lock()
	defer ks.mu.Unlock()

	delete(ks.sites, siteURL)
	return ks.save()
}

func (ks *Keystore) save() error {
	data, err := json.MarshalIndent(ks.sites, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(ks.filePath, data, 0600)
}
