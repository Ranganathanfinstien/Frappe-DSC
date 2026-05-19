//go:build !windows && !darwin

package main

import "fmt"

// PostInstall is a no-op on non-Windows platforms. The autostart, firewall,
// and certificate-trust steps are Windows-specific concepts handled by the
// MSI installer; on macOS we use a LaunchAgent .plist and on Linux a
// systemd user service — both wired up by their respective packagers, not
// by the bridge binary itself.
func PostInstall() error {
	return fmt.Errorf("--post-install is only meaningful on Windows")
}

// PreUninstall mirrors PostInstall.
func PreUninstall() error {
	return fmt.Errorf("--pre-uninstall is only meaningful on Windows")
}
