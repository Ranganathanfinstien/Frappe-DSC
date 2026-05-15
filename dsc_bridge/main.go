package main

import (
	"flag"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"

	"fyne.io/systray"
)

func main() {
	// Hooks called by the MSI installer at install / uninstall time. Both
	// must complete and exit without starting the HTTP server or the tray
	// icon — the installer waits for the process to return.
	doPostInstall := flag.Bool("post-install", false, "Run post-install setup (MSI hook) and exit")
	doPreUninstall := flag.Bool("pre-uninstall", false, "Run pre-uninstall cleanup (MSI hook) and exit")
	flag.Parse()

	if *doPostInstall {
		if err := PostInstall(); err != nil {
			log.Fatalf("post-install failed: %v", err)
		}
		return
	}
	if *doPreUninstall {
		if err := PreUninstall(); err != nil {
			log.Fatalf("pre-uninstall failed: %v", err)
		}
		return
	}

	// Load configuration
	cfg, err := LoadConfig()
	if err != nil {
		log.Fatalf("Failed to load config: %v", err)
	}

	// Redirect logs to a file in the data dir — on Windows the exe is built
	// with -H windowsgui so stderr is detached; without this, every log line
	// is silently discarded and field debugging is impossible.
	logPath := filepath.Join(cfg.DataDir, "bridge.log")
	if lf, err := os.OpenFile(logPath, os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0600); err == nil {
		log.SetOutput(lf)
		log.SetFlags(log.LstdFlags | log.Lmicroseconds)
		log.Printf("=== dsc-bridge v%s starting ===", AgentVersion)
		log.Printf("DataDir: %s", cfg.DataDir)
		log.Printf("PKCS11 libs configured: %d", len(cfg.PKCS11Libs))
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
