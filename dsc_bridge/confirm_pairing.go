package main

import (
	"log"
	"os"
)

// autoConfirmEnv, when set to a truthy value ("1", "true", "yes"), bypasses the
// interactive pairing confirmation. It exists solely for headless/CI/dev
// environments where no desktop dialog backend is available. On a real user
// desktop (the production target) a native dialog is always present, so this
// should never be set there.
const autoConfirmEnv = "DSC_BRIDGE_AUTO_CONFIRM_PAIRING"

// confirmPairing asks the human at the keyboard to approve a new pairing with
// siteURL before the agent contacts that site or stores any credential.
//
// This is the primary defense against silent, drive-by pairing: a malicious web
// page can POST to the loopback /v1/pair endpoint, but it cannot click this
// dialog. The user sees exactly which site is asking and can refuse an
// unexpected origin (e.g. an attacker-controlled Frappe clone).
//
// Resolution order:
//  1. If autoConfirmEnv is truthy, approve (headless/CI/dev escape hatch).
//  2. Otherwise show the platform-native dialog and honor the user's choice.
//  3. If no dialog backend is available, DENY — secure by default. The escape
//     hatch above exists precisely so headless setups can opt back in.
func confirmPairing(siteURL string) bool {
	if isTruthy(os.Getenv(autoConfirmEnv)) {
		log.Printf("pairing: %s set — auto-approving pairing with %s", autoConfirmEnv, siteURL)
		return true
	}

	allowed, ok := confirmPairingDialog(siteURL)
	if !ok {
		log.Printf("pairing: no confirmation dialog available; denying pairing with %s "+
			"(set %s=1 to allow on headless hosts)", siteURL, autoConfirmEnv)
		return false
	}
	if !allowed {
		log.Printf("pairing: user declined pairing with %s", siteURL)
	}
	return allowed
}

func isTruthy(v string) bool {
	switch v {
	case "1", "true", "TRUE", "True", "yes", "YES", "Yes", "on", "ON":
		return true
	default:
		return false
	}
}
