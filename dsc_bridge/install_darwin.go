//go:build darwin

package main

// Post-install / pre-uninstall hooks invoked by the macOS .pkg installer.
//
// Unlike Windows where we use a registry Run key + Service Control Manager
// concepts, macOS expects:
//   - Cert trust: stored in the login Keychain (or System Keychain when
//     installed with admin privileges by the .pkg). We use `security` CLI.
//   - Autostart: a LaunchAgent .plist under ~/Library/LaunchAgents loaded by
//     `launchctl`. LaunchAgents run as the logged-in user (which is what we
//     want — a tray app needs a user session), unlike LaunchDaemons which
//     run as root with no GUI.
//   - Firewall: macOS Application Firewall is off by default and is
//     interactive — we do nothing here. If a user has it enabled they'll
//     get a one-time "Allow incoming connections?" popup on first bind.

import (
	"fmt"
	"log"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"strings"
)

const (
	launchAgentLabel = "com.esign.dsc-bridge"
)

func PostInstall() error {
	cfg, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("load config: %w", err)
	}

	// Generate the TLS cert now so we can install it to the user's Keychain.
	// EnsureTLSCert is a no-op when both cert and key already exist.
	if _, _, err := EnsureTLSCert(cfg); err != nil {
		return fmt.Errorf("generate cert: %w", err)
	}

	if err := installCertToKeychain(cfg.TLSCertPath); err != nil {
		log.Printf("keychain-trust: %v (browser will warn on first connection until trusted manually)", err)
	}

	exe, err := exeFullPath()
	if err != nil {
		return fmt.Errorf("resolve exe path: %w", err)
	}

	plistPath, err := writeLaunchAgent(exe)
	if err != nil {
		return fmt.Errorf("write LaunchAgent: %w", err)
	}

	if err := loadLaunchAgent(plistPath); err != nil {
		log.Printf("launchctl load: %v (signer can start the bridge manually until next login)", err)
	}

	log.Println("post-install: complete")
	return nil
}

func PreUninstall() error {
	plistPath, err := launchAgentPath()
	if err == nil {
		if err := unloadLaunchAgent(plistPath); err != nil {
			log.Printf("launchctl unload: %v", err)
		}
		if rerr := os.Remove(plistPath); rerr != nil && !os.IsNotExist(rerr) {
			log.Printf("plist-remove: %v", rerr)
		}
	}

	cfg, cerr := LoadConfig()
	if cerr == nil {
		if err := removeCertFromKeychain(cfg.TLSCertPath); err != nil {
			log.Printf("keychain-remove: %v", err)
		}
	}

	log.Println("pre-uninstall: complete")
	return nil
}

func installCertToKeychain(certPath string) error {
	// `-d` would target the admin (System) keychain and requires root. The
	// .pkg postinstall runs as root, so this puts the cert in the System
	// keychain where every user on the Mac trusts it.
	cmd := exec.Command("security",
		"add-trusted-cert",
		"-d",
		"-r", "trustRoot",
		"-k", "/Library/Keychains/System.keychain",
		certPath,
	)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("security add-trusted-cert: %w (output: %s)", err, strings.TrimSpace(string(out)))
	}
	return nil
}

func removeCertFromKeychain(certPath string) error {
	cmd := exec.Command("security", "delete-certificate", "-c", "dsc-bridge", "/Library/Keychains/System.keychain")
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("security delete-certificate: %w (output: %s)", err, strings.TrimSpace(string(out)))
	}
	return nil
}

func launchAgentDir() (string, error) {
	usr, err := user.Current()
	if err != nil {
		return "", err
	}
	return filepath.Join(usr.HomeDir, "Library", "LaunchAgents"), nil
}

func launchAgentPath() (string, error) {
	dir, err := launchAgentDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, launchAgentLabel+".plist"), nil
}

func writeLaunchAgent(exePath string) (string, error) {
	dir, err := launchAgentDir()
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	path := filepath.Join(dir, launchAgentLabel+".plist")

	// RunAtLoad → start on login. KeepAlive → restart if the agent ever
	// crashes. StandardOutPath/ErrorPath → write logs so support can see
	// startup failures without attaching to the process.
	plist := fmt.Sprintf(`<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>%s</string>
    <key>ProgramArguments</key>
    <array>
        <string>%s</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/dsc-bridge.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/dsc-bridge.err.log</string>
</dict>
</plist>
`, launchAgentLabel, exePath)

	if err := os.WriteFile(path, []byte(plist), 0o644); err != nil {
		return "", err
	}
	return path, nil
}

func loadLaunchAgent(plistPath string) error {
	// `bootstrap gui/<uid>` is the modern replacement for `launchctl load`.
	// We fall back to `load` for older macOS versions if bootstrap fails.
	uid := os.Getuid()
	if cmd := exec.Command("launchctl", "bootstrap", fmt.Sprintf("gui/%d", uid), plistPath); cmd.Run() == nil {
		return nil
	}
	cmd := exec.Command("launchctl", "load", "-w", plistPath)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("launchctl load: %w (output: %s)", err, strings.TrimSpace(string(out)))
	}
	return nil
}

func unloadLaunchAgent(plistPath string) error {
	uid := os.Getuid()
	if cmd := exec.Command("launchctl", "bootout", fmt.Sprintf("gui/%d/%s", uid, launchAgentLabel)); cmd.Run() == nil {
		return nil
	}
	cmd := exec.Command("launchctl", "unload", plistPath)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("launchctl unload: %w (output: %s)", err, strings.TrimSpace(string(out)))
	}
	return nil
}

func exeFullPath() (string, error) {
	exe, err := os.Executable()
	if err != nil {
		return "", err
	}
	return filepath.Clean(exe), nil
}
