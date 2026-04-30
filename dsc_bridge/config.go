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
// The bridge is vendor-agnostic: any compliant PKCS#11 module from this list
// (or added via dsc-bridge.json `pkcs11_libs`) is loaded at startup and its
// tokens enumerated. Missing libraries are silently skipped.
func DefaultPKCS11Paths() []string {
	switch runtime.GOOS {
	case "windows":
		sys32 := os.Getenv("SystemRoot") + `\System32`
		pf := os.Getenv("ProgramFiles")
		pfx86 := os.Getenv("ProgramFiles(x86)")
		paths := []string{
			// --- WatchData ProxKey (CryptoPlanet, Pagaria, etc.) ---
			filepath.Join(sys32, "SignatureP11.dll"),
			filepath.Join(sys32, "WDPKCS.dll"),
			filepath.Join(sys32, "WDPKCS11.dll"),
			// --- Feitian ePass2003 (eMudhra, Capricorn, Sify, (n)Code, Pantasign) ---
			filepath.Join(sys32, "eps2003csp11.dll"),
			filepath.Join(sys32, "eps2003csp11_v2.dll"),
			filepath.Join(sys32, "ShuttleCsp11_3000.dll"),
			filepath.Join(sys32, "ep3003csp11.dll"), // ePass3003
			// --- Feitian generic / Hypersecu HyperPKI (uses Castle library) ---
			filepath.Join(sys32, "castle_v3.dll"),
			filepath.Join(sys32, "castle.dll"),
			filepath.Join(sys32, "pkcs11hw.dll"),
			filepath.Join(sys32, "ftepkcs11.dll"),
			filepath.Join(sys32, "ngp11v211.dll"),
			// --- mToken K9 / CryptoID ---
			filepath.Join(sys32, "mToken CryptoID PKCS11.dll"),
			// --- TrustKey ---
			filepath.Join(sys32, "TrustKeyP11.dll"),
			// --- SafeNet / Aladdin / Thales eToken ---
			filepath.Join(sys32, "eTPKCS11.dll"),
			// --- Athena IDProtect ---
			filepath.Join(sys32, "asepkcs.dll"),
			// --- A.E.T. SafeSign ---
			filepath.Join(sys32, "aetpkcs11.dll"),
			// --- Yubikey ---
			filepath.Join(sys32, "ykcs11.dll"),
			// --- OpenSC (generic) ---
			filepath.Join(sys32, "opensc-pkcs11.dll"),
		}
		// Vendors that install under Program Files instead of System32
		for _, base := range []string{pf, pfx86} {
			if base == "" {
				continue
			}
			paths = append(paths,
				filepath.Join(base, "HYP", "HYP PKI Manager", "pkcs11hw.dll"),
				filepath.Join(base, "Hypersecu", "HyperPKI", "castle_v3.dll"),
				filepath.Join(base, "Hypersecu", "PKCS11", "castle_v3.dll"),
				filepath.Join(base, "OpenSC Project", "OpenSC", "pkcs11", "opensc-pkcs11.dll"),
				filepath.Join(base, "Yubico", "Yubico PIV Tool", "bin", "libykcs11.dll"),
			)
		}
		return paths
	case "linux":
		return []string{
			// --- SoftHSM2 (testing) ---
			"/usr/lib/softhsm/libsofthsm2.so",
			"/usr/lib/x86_64-linux-gnu/softhsm/libsofthsm2.so",
			"/usr/lib64/softhsm/libsofthsm2.so",
			// --- OpenSC (generic) ---
			"/usr/lib/x86_64-linux-gnu/opensc-pkcs11.so",
			"/usr/lib/opensc-pkcs11.so",
			"/usr/lib64/opensc-pkcs11.so",
			"/usr/local/lib/opensc-pkcs11.so",
			// --- SafeNet / Aladdin eToken ---
			"/usr/lib/libeTPkcs11.so",
			"/usr/lib/x86_64-linux-gnu/libeTPkcs11.so",
			"/usr/lib64/libeTPkcs11.so",
			// --- Feitian / Hypersecu (Castle) ---
			"/usr/lib/libcastle.so",
			"/usr/lib/libcastle_v3.so",
			"/usr/lib/x86_64-linux-gnu/libcastle.so",
			"/usr/lib/libes2003.so",
			// --- WatchData ProxKey (rarely available on Linux) ---
			"/usr/lib/libwdpkcs.so",
			"/usr/lib/libProxKeyP11.so",
			// --- Yubikey ---
			"/usr/lib/x86_64-linux-gnu/libykcs11.so",
			"/usr/lib/libykcs11.so",
			"/usr/lib64/libykcs11.so",
			// --- p11-kit aggregator ---
			"/usr/lib/x86_64-linux-gnu/pkcs11/p11-kit-trust.so",
		}
	case "darwin":
		return []string{
			// --- SoftHSM2 (testing) ---
			"/usr/local/lib/softhsm/libsofthsm2.so",
			"/opt/homebrew/lib/softhsm/libsofthsm2.so",
			// --- OpenSC (generic) ---
			"/Library/OpenSC/lib/opensc-pkcs11.so",
			"/usr/local/lib/opensc-pkcs11.so",
			"/opt/homebrew/lib/opensc-pkcs11.so",
			// --- SafeNet eToken ---
			"/Library/Frameworks/eToken.framework/Versions/A/libeTPkcs11.dylib",
			// --- Yubikey ---
			"/usr/local/lib/libykcs11.dylib",
			"/opt/homebrew/lib/libykcs11.dylib",
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
