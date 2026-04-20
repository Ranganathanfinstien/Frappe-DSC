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

# Initialize a test token
softhsm2-util --init-token --slot 0 --label "TestDSC" --pin 1234 --so-pin 5678

# Generate a key pair
pkcs11-tool --module /usr/lib/softhsm/libsofthsm2.so \
  --login --pin 1234 \
  --keypairgen --key-type rsa:2048 --id 01 --label "TestKey"

# Run the agent
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
