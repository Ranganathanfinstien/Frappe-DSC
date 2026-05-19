# Settings (DSC Settings)

**DSC Settings** is a Single doctype holding the app's global configuration. Open it
from the **DSC Signing** workspace.

## Agent

| Setting | Purpose |
|---|---|
| **Agent listen port** | The localhost port the [bridge agent](bridge-agent.md) listens on. Must match the agent's configuration. Default `4645`. |

## Signing

| Setting | Purpose |
|---|---|
| **Default hash algorithm** | Hash used when building the PAdES `SignedAttrs`. `sha256` recommended. |
| **Default reason** | Default "Reason" text shown in the signature stamp. |
| **Default location** | Fallback location text when signer geolocation is unavailable. |

## Signer location

| Setting | Purpose |
|---|---|
| **Enforce signer location** | When on, signers must share their browser location before signing. Enforced server-side — it cannot be bypassed by tampered JavaScript. The resolved address is recorded on the signing request and can appear in the stamp. |

## Trust store

| Setting | Purpose |
|---|---|
| **Custom CA Trust Store Bundle** | Optional PEM bundle of **additional** CAs to trust during verification. All CCA India CAs are already trusted by the built-in bundle — only use this to add other CAs. See [Trust Store](trust-store.md). |

## Retention & cleanup

The app runs scheduled maintenance automatically (via `scheduler_events`):

| Schedule | Task |
|---|---|
| Daily | Notify users of upcoming certificate expiries |
| Daily | Purge old signing requests beyond the retention window |
| Hourly | Expire stale **Pending** requests |

Retention windows are configured in DSC Settings.

## Security notes

- A server-side **HMAC secret** authenticates the browser ↔ agent ↔ server handshake.
  It is generated on demand and stored on the server; it is never exposed to the
  browser.
- The token PIN and private key never reach the server — only the final signature
  bytes do.
- Signed PDFs are marked with an `is_dsc_signed` flag on the **File** record and are
  protected from deletion by non-administrators.
</content>
