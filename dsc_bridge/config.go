package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
)

const (
	DefaultPort    = 4645
	DefaultHost    = "127.0.0.1"
	AgentVersion   = "1.0.0"
	ConfigFileName = "dsc-bridge.json"
)

// Config holds the agent configuration.
type Config struct {
	Host          string   `json:"host"`
	Port          int      `json:"port"`
	PKCS11Libs    []string `json:"pkcs11_libs"`
	DataDir       string   `json:"-"`
	TLSCertPath   string   `json:"-"`
	TLSKeyPath    string   `json:"-"`
	PairedSites   string   `json:"-"` // path to paired_sites.json
}

// DefaultPKCS11Paths returns known PKCS#11 library paths per platform.
func DefaultPKCS11Paths() []string {
	switch runtime.GOOS {
	case "windows":
		sys32 := os.Getenv("SystemRoot") + `\System32`
		return []string{
			filepath.Join(sys32, "eps2003csp11.dll"),           // eMudhra ePass2003
			filepath.Join(sys32, "SignatureP11.dll"),           // WatchData ProxKey, HYP2003
			filepath.Join(sys32, "WDPKCS.dll"),                 // WatchData (legacy bundled lib)
			filepath.Join(sys32, "mToken CryptoID PKCS11.dll"), // mToken K9
			filepath.Join(sys32, "eTPKCS11.dll"),               // SafeNet
		}
	case "linux":
		return []string{
			"/usr/lib/softhsm/libsofthsm2.so",       // SoftHSM2 (testing)
			"/usr/lib/x86_64-linux-gnu/opensc-pkcs11.so",
			"/usr/lib/libeTPkcs11.so",
		}
	case "darwin":
		return []string{
			"/usr/local/lib/softhsm/libsofthsm2.so",
			"/Library/OpenSC/lib/opensc-pkcs11.so",
		}
	default:
		return nil
	}
}

// LoadConfig reads config from the data directory, falling back to defaults.
func LoadConfig() (*Config, error) {
	dataDir, err := getDataDir()
	if err != nil {
		return nil, err
	}

	cfg := &Config{
		Host:        DefaultHost,
		Port:        DefaultPort,
		PKCS11Libs:  DefaultPKCS11Paths(),
		DataDir:     dataDir,
		TLSCertPath: filepath.Join(dataDir, "tls_cert.pem"),
		TLSKeyPath:  filepath.Join(dataDir, "tls_key.pem"),
		PairedSites: filepath.Join(dataDir, "paired_sites.json"),
	}

	configPath := filepath.Join(dataDir, ConfigFileName)
	data, err := os.ReadFile(configPath)
	if err != nil {
		// Config file doesn't exist yet — use defaults
		if os.IsNotExist(err) {
			return cfg, nil
		}
		return nil, err
	}

	// Merge file config over defaults
	var fileCfg struct {
		Host       string   `json:"host"`
		Port       int      `json:"port"`
		PKCS11Libs []string `json:"pkcs11_libs"`
	}
	if err := json.Unmarshal(data, &fileCfg); err != nil {
		return nil, err
	}

	if fileCfg.Host != "" {
		cfg.Host = fileCfg.Host
	}
	if fileCfg.Port != 0 {
		cfg.Port = fileCfg.Port
	}
	if len(fileCfg.PKCS11Libs) > 0 {
		cfg.PKCS11Libs = fileCfg.PKCS11Libs
	}

	return cfg, nil
}

// getDataDir returns the OS-appropriate data directory for dsc-bridge.
func getDataDir() (string, error) {
	var base string
	switch runtime.GOOS {
	case "windows":
		base = os.Getenv("LOCALAPPDATA")
	case "darwin":
		home, _ := os.UserHomeDir()
		base = filepath.Join(home, "Library", "Application Support")
	default:
		base = os.Getenv("XDG_DATA_HOME")
		if base == "" {
			home, _ := os.UserHomeDir()
			base = filepath.Join(home, ".local", "share")
		}
	}

	dir := filepath.Join(base, "dsc-bridge")
	if err := os.MkdirAll(dir, 0700); err != nil {
		return "", err
	}
	return dir, nil
}
