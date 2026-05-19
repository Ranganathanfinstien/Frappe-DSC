# Bridge Agent

The **bridge agent** (`dsc_bridge/`) is a small desktop program that physically talks
to the DSC USB token. It is the only component that touches the token's private key
and PIN — the Frappe server never does.

## Why a separate agent?

A web browser cannot access a PKCS#11 hardware token directly and securely. The
bridge agent runs locally, exposes an HTTPS endpoint on `127.0.0.1`, and performs the
cryptographic signing on the token. The browser relays data between the Frappe server
and the agent.

## What it is

- Written in **Go**, source under `dsc_bridge/`.
- Builds for **Windows** and **macOS** (`install_windows.go`, `install_darwin.go`).
- Communicates with the token over **PKCS#11** (`pkcs11_handler.go`).
- Serves a localhost HTTPS API (`server.go`, `tls.go`).

## Installation

1. Obtain the installer for the signer's operating system.
2. Run it. On Windows an MSI is produced via the WiX packaging
   (`wix.json`, `windows-package/`).
3. The agent starts in the background and listens on `https://127.0.0.1:<port>`
   (default port `4645`, configurable to match **DSC Settings → Agent listen port**).

## Pairing

Before it can be used, the agent must be **paired** to a Frappe user:

1. In Frappe, create a **DSC Agent Registration** and click **Generate Pairing Code**.
2. Enter that code in the bridge agent.
3. The agent and the server now share a secret used to authenticate signing requests.

The shared secret backs an **HMAC** that protects each signing handshake against
tampering and replay — the browser cannot forge it because it never holds the secret.

## The signing handshake

```
1. Browser → Agent   : fetch token certificate
2. Browser → Server  : initiate (sends certificate)
3. Server → Browser  : session id + hash to sign + HMAC
4. Browser → Agent   : sign this hash  (agent prompts for token PIN)
5. Agent  → Browser  : signature bytes
6. Browser → Server  : finalize (sends signature)
```

The token PIN is entered locally in the agent and never leaves the machine.

## Requirements

- The DSC token's **vendor PKCS#11 driver** must be installed.
- The token must be plugged in before signing.
- The agent must be running.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| "Could not reach the signing agent" | Agent not running, or wrong port in DSC Settings |
| "No token found" | Token unplugged, or vendor driver not installed |
| "Certificate mismatch" | Token's certificate differs from the one on the DSC Profile |
| Signing hangs at PIN | PIN dialog opened behind another window |

See also the agent's own `dsc_bridge/README.md`.
</content>
