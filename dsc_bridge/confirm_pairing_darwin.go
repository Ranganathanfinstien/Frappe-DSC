//go:build darwin

package main

import (
	"os/exec"
)

// confirmPairingDialog shows a native macOS dialog via osascript asking the user
// to approve pairing with siteURL. Returns (allowed, ok); ok is false only if
// osascript cannot be located (it ships with every macOS, so that is rare).
func confirmPairingDialog(siteURL string) (bool, bool) {
	bin, err := exec.LookPath("osascript")
	if err != nil {
		return false, false
	}

	// osascript with literal -e args; siteURL is passed as a separate argument
	// to the AppleScript "on run argv" handler, so it cannot break out of the
	// script string. Exit code 0 = "Allow", non-zero (incl. user cancel) = deny.
	script := `on run argv
	set siteURL to item 1 of argv
	display dialog "A site is requesting to pair with this signing agent:" & return & return & siteURL & return & return & "Only approve this if you just started pairing from that site. Approving lets it request digital signatures from your token." with title "DSC Bridge — Pairing Request" buttons {"Deny", "Allow"} default button "Deny" with icon caution
	if button returned of result is "Allow" then
		return 0
	else
		error number 1
	end if
end run`

	cmd := exec.Command(bin, "-e", script, siteURL)
	if err := cmd.Run(); err != nil {
		// Non-zero exit means the user chose Deny / dismissed the dialog.
		return false, true
	}
	return true, true
}
