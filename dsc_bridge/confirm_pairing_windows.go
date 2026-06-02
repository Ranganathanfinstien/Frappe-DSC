//go:build windows

package main

import (
	"unsafe"

	"golang.org/x/sys/windows"
)

// MessageBoxW flags.
const (
	mbYesNo         = 0x00000004
	mbIconWarning   = 0x00000030
	mbDefButton2    = 0x00000100 // default the focused button to "No"
	mbSystemModal   = 0x00001000 // stay on top of other windows
	mbSetForeground = 0x00010000
	idYes           = 6
)

// confirmPairingDialog shows a native Windows MessageBox asking the user to
// approve pairing with siteURL. Returns (allowed, true); the second value is
// always true because user32!MessageBoxW is always available on Windows.
func confirmPairingDialog(siteURL string) (bool, bool) {
	user32 := windows.NewLazySystemDLL("user32.dll")
	messageBox := user32.NewProc("MessageBoxW")

	title, _ := windows.UTF16PtrFromString("DSC Bridge — Pairing Request")
	text, _ := windows.UTF16PtrFromString(
		"A site is requesting to pair with this signing agent:\n\n" +
			siteURL +
			"\n\nOnly approve this if you just started pairing from that site. " +
			"Approving lets it request digital signatures from your token.\n\n" +
			"Allow pairing?",
	)

	ret, _, _ := messageBox.Call(
		0,
		uintptr(unsafe.Pointer(text)),
		uintptr(unsafe.Pointer(title)),
		uintptr(mbYesNo|mbIconWarning|mbDefButton2|mbSystemModal|mbSetForeground),
	)
	return int(ret) == idYes, true
}
