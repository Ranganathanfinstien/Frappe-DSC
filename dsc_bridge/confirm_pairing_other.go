//go:build !windows && !darwin

package main

import (
	"os/exec"
)

// confirmPairingDialog shows a native Linux/BSD dialog via zenity or kdialog,
// asking the user to approve pairing with siteURL. Returns (allowed, ok); ok is
// false when neither tool is installed, in which case confirmPairing falls back
// to its secure default (deny, unless the auto-confirm env var is set).
func confirmPairingDialog(siteURL string) (bool, bool) {
	const body = "A site is requesting to pair with this signing agent:\n\n" +
		"%s\n\n" +
		"Only approve this if you just started pairing from that site. " +
		"Approving lets it request digital signatures from your token."

	text := sprintfSite(body, siteURL)

	if bin, err := exec.LookPath("zenity"); err == nil {
		// zenity: exit 0 = OK/yes, non-zero = No/closed. siteURL is interpolated
		// into --text only (not a shell), so there is no injection surface.
		cmd := exec.Command(bin,
			"--question",
			"--title=DSC Bridge — Pairing Request",
			"--ok-label=Allow",
			"--cancel-label=Deny",
			"--default-cancel",
			"--text="+text,
		)
		return cmd.Run() == nil, true
	}

	if bin, err := exec.LookPath("kdialog"); err == nil {
		cmd := exec.Command(bin,
			"--title", "DSC Bridge — Pairing Request",
			"--yesno", text,
		)
		return cmd.Run() == nil, true
	}

	return false, false
}

// sprintfSite substitutes a single %s in body with siteURL without pulling in
// fmt at every call site; kept tiny and dependency-free.
func sprintfSite(body, siteURL string) string {
	out := make([]byte, 0, len(body)+len(siteURL))
	for i := 0; i < len(body); i++ {
		if i+1 < len(body) && body[i] == '%' && body[i+1] == 's' {
			out = append(out, siteURL...)
			i++
			continue
		}
		out = append(out, body[i])
	}
	return string(out)
}
