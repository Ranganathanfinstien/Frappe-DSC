# dsc-bridge — Desktop Agent for DSC Signing

A Go application that bridges the browser and USB DSC tokens via PKCS#11.
Runs on the signer's machine, listens on `https://127.0.0.1:4645`.

## Prerequisites

- Go 1.22+
- PKCS#11 library for your USB token (or SoftHSM2 for testing)

## Build

```bash
cd dsc_bridge
go mod tidy
go build -o dsc-bridge .
```

## Test with SoftHSM2

```bash
# Install SoftHSM2
sudo apt install softhsm2 opensc

# Initialise the test token + import a self-signed cert (idempotent)
./test_setup.sh

# Run the integration tests against the SoftHSM2 token
./build.sh integration
# (equivalent to: go test -tags softhsm -v ./...)

# Run the agent itself
./dsc-bridge
```

## Configuration

Optional config file at `~/.local/share/dsc-bridge/dsc-bridge.json`:

```json
{
  "host": "127.0.0.1",
  "port": 4645,
  "pkcs11_libs": ["/usr/lib/softhsm/libsofthsm2.so"]
}
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/status` | Agent status, detected tokens, paired sites |
| GET | `/v1/certs` | List certificates on plugged-in tokens (no PIN) |
| POST | `/v1/pair` | Pair agent with a Frappe site |
| POST | `/v1/sign` | Sign a hash using a specific certificate |

## Security

- HTTPS only (self-signed cert, fingerprint exchanged during pairing)
- Listens only on 127.0.0.1 (localhost)
- All requests (except /v1/pair and /v1/status) require `X-DSC-Site-Token` and `Origin` headers
- Private key never leaves the USB token
- Site tokens are stored in the **OS keychain** (Windows Credential Manager / macOS Keychain / Linux libsecret), not on disk

## Windows MSI

The CI workflow at `.github/workflows/dsc-bridge-msi.yml` builds a signed
MSI installer on `windows-latest`:

- Installs WiX Toolset v3 and `go-msi`
- Builds `dsc-bridge.exe` with `-H windowsgui` (no console window)
- Generates the MSI from `wix.json` (registers `dsc-bridge` as a Windows Service)
- Optionally Authenticode-signs if the repo has the secrets:
  - `CODE_SIGNING_PFX_BASE64` — base64 of the `.pfx` code-signing certificate
  - `CODE_SIGNING_PFX_PASSWORD` — password for the pfx
- Uploads the MSI as a workflow artifact

Trigger manually via **Actions → dsc-bridge MSI → Run workflow**, or push
changes under `dsc_bridge/`.
