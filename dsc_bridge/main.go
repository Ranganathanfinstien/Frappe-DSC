package main

import (
	"log"
	"os"
	"os/signal"
	"syscall"

	"fyne.io/systray"
)

func main() {
	// Load configuration
	cfg, err := LoadConfig()
	if err != nil {
		log.Fatalf("Failed to load config: %v", err)
	}

	// Ensure TLS certificate exists
	tlsCert, agentFP, err := EnsureTLSCert(cfg)
	if err != nil {
		log.Fatalf("Failed to setup TLS: %v", err)
	}
	log.Printf("Agent fingerprint: %s", agentFP)

	// Load keystore (paired sites)
	ks, err := NewKeystore(cfg.PairedSites)
	if err != nil {
		log.Fatalf("Failed to load keystore: %v", err)
	}

	// Initialize PKCS#11 handler
	pkcs11Handler := NewPKCS11Handler(cfg.PKCS11Libs)
	defer pkcs11Handler.Destroy()

	// Start HTTPS server in background
	go func() {
		if err := StartServer(cfg, tlsCert, agentFP, pkcs11Handler, ks); err != nil {
			log.Fatalf("Server error: %v", err)
		}
	}()

	// Start system tray icon
	go systray.Run(onTrayReady(agentFP), onTrayExit)

	// Wait for shutdown signal
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	<-sigCh

	log.Println("Shutting down dsc-bridge...")
	systray.Quit()
}

func onTrayReady(agentFP string) func() {
	return func() {
		systray.SetTitle("DSC Bridge")
		systray.SetTooltip("DSC Bridge Agent — Digital Signature Service")

		mStatus := systray.AddMenuItem("Status: Running", "Agent is running")
		mStatus.Disable()

		systray.AddSeparator()

		mFP := systray.AddMenuItem("Fingerprint: "+agentFP[:16]+"...", "Agent TLS fingerprint")
		mFP.Disable()

		systray.AddSeparator()

		mQuit := systray.AddMenuItem("Quit", "Stop dsc-bridge")

		go func() {
			<-mQuit.ClickedCh
			systray.Quit()
			os.Exit(0)
		}()
	}
}

func onTrayExit() {
	log.Println("Tray exited")
}
