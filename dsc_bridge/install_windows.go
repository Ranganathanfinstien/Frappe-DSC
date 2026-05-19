//go:build windows

package main

// Post-install / pre-uninstall hooks invoked by the MSI installer.
//
// The bridge is a system-tray GUI agent, NOT a Windows Service.
// Services run in Session 0 with no desktop access, so a systray app
// inside a service produces no visible icon and often hangs at startup.
//
// Instead we use the standard mechanism for per-user GUI agents:
//   - Auto-start: HKLM\...\Run registry key for all users
//   - Firewall: netsh rule for inbound TCP 4645 on the bridge binary
//   - Trust: certutil adds the bridge's self-signed cert to the local
//            machine's Trusted Root store so the browser stops warning.

import (
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"golang.org/x/sys/windows/registry"
)

const (
	runKeyPath      = `SOFTWARE\Microsoft\Windows\CurrentVersion\Run`
	runKeyValueName = "DSC Bridge"
	firewallRuleNm  = "DSC Bridge Agent"
	certStoreName   = "Root"
)

// PostInstall is invoked once by the MSI immediately after files are placed.
// It must be idempotent — re-running it should not produce duplicate firewall
// rules, duplicate trust-store entries, or extra registry values.
func PostInstall() error {
	cfg, err := LoadConfig()
	if err != nil {
		return fmt.Errorf("load config: %w", err)
	}

	// 1. Generate the TLS cert now so we can immediately install it to the
	//    trust store. EnsureTLSCert is a no-op if cert already exists.
	if _, _, err := EnsureTLSCert(cfg); err != nil {
		return fmt.Errorf("generate cert: %w", err)
	}

	if err := installCertToTrustStore(cfg.TLSCertPath); err != nil {
		log.Printf("install-cert: %v (continuing; browser may warn until trusted manually)", err)
	}

	exe, err := exeFullPath()
	if err != nil {
		return fmt.Errorf("resolve exe path: %w", err)
	}

	if err := addFirewallRule(exe); err != nil {
		log.Printf("firewall-rule: %v (continuing; signers may hit a Windows Defender prompt)", err)
	}

	if err := addAutoStartEntry(exe); err != nil {
		return fmt.Errorf("autostart: %w", err)
	}

	log.Println("post-install: complete")
	return nil
}

// PreUninstall reverses the steps from PostInstall. Best-effort: each step
// logs but does not abort, so a partial state never blocks uninstall.
func PreUninstall() error {
	if err := removeAutoStartEntry(); err != nil {
		log.Printf("autostart-remove: %v", err)
	}
	if err := removeFirewallRule(); err != nil {
		log.Printf("firewall-remove: %v", err)
	}

	cfg, err := LoadConfig()
	if err == nil {
		if err := removeCertFromTrustStore(cfg.TLSCertPath); err != nil {
			log.Printf("cert-remove: %v", err)
		}
	}

	log.Println("pre-uninstall: complete")
	return nil
}

func installCertToTrustStore(certPath string) error {
	// `-f` overwrites an existing matching entry so re-install is idempotent.
	cmd := exec.Command("certutil", "-f", "-addstore", certStoreName, certPath)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("certutil addstore: %w (output: %s)", err, strings.TrimSpace(string(out)))
	}
	return nil
}

func removeCertFromTrustStore(certPath string) error {
	// certutil -delstore needs the cert's SHA-1 hash or subject CN. We use
	// the CN set in generateSelfSignedCert (tls.go).
	cmd := exec.Command("certutil", "-delstore", certStoreName, "dsc-bridge")
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("certutil delstore: %w (output: %s)", err, strings.TrimSpace(string(out)))
	}
	return nil
}

func addFirewallRule(exePath string) error {
	// `netsh advfirewall firewall add rule` errors if a rule with the same
	// name already exists; we remove it first to keep the operation idempotent.
	_ = exec.Command("netsh", "advfirewall", "firewall", "delete", "rule",
		"name="+firewallRuleNm).Run()

	cmd := exec.Command("netsh", "advfirewall", "firewall", "add", "rule",
		"name="+firewallRuleNm,
		"dir=in",
		"action=allow",
		"program="+exePath,
		"protocol=TCP",
		"localport=4645",
		"enable=yes",
		"profile=any",
	)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("netsh add rule: %w (output: %s)", err, strings.TrimSpace(string(out)))
	}
	return nil
}

func removeFirewallRule() error {
	cmd := exec.Command("netsh", "advfirewall", "firewall", "delete", "rule",
		"name="+firewallRuleNm)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("netsh delete rule: %w (output: %s)", err, strings.TrimSpace(string(out)))
	}
	return nil
}

func addAutoStartEntry(exePath string) error {
	key, _, err := registry.CreateKey(registry.LOCAL_MACHINE, runKeyPath, registry.SET_VALUE)
	if err != nil {
		return fmt.Errorf("open HKLM\\Run: %w", err)
	}
	defer key.Close()
	// Quote the path so spaces in "Program Files" do not split the command.
	return key.SetStringValue(runKeyValueName, `"`+exePath+`"`)
}

func removeAutoStartEntry() error {
	key, err := registry.OpenKey(registry.LOCAL_MACHINE, runKeyPath, registry.SET_VALUE)
	if err != nil {
		return fmt.Errorf("open HKLM\\Run: %w", err)
	}
	defer key.Close()
	if err := key.DeleteValue(runKeyValueName); err != nil && err != registry.ErrNotExist {
		return fmt.Errorf("delete value: %w", err)
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
