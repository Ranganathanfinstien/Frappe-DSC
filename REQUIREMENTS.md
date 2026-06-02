# Requirements

Everything needed for **e_sign** to actually work end-to-end.

`bench install-app e_sign` only installs the **server (Python) side**. PDF
signing also needs the **DSC Bridge desktop agent** and the **token driver** on
the signer's machine. The items marked **Manual** below are NOT installed
automatically — install them or signing will fail.

---

## 1. Server side (Frappe app) — auto-installed

Installed automatically by `bench install-app` from `pyproject.toml`:

| Requirement | Version | How |
| --- | --- | --- |
| Frappe / ERPNext | `>=15.0.0,<16.0.0` | Managed by bench |
| Python | `>=3.10` | Bench environment |
| pyhanko[image-support] | latest | pip (via pyproject.toml) |
| asn1crypto | latest | pip (via pyproject.toml) |

`e_sign/install.py` (`after_install`) also runs automatically and adds the
`is_dsc_signed` custom field to the File doctype.

```bash
bench get-app e_sign <repo-url>
bench --site <your-site> install-app e_sign
```

---

## 2. Desktop agent (DSC Bridge) — **Manual**

Runs on the **signer's machine** (where the USB token is plugged in), not on the
server. Without it, the browser cannot reach the token.

Dependencies are declared in `dsc_bridge/go.mod` and pulled automatically by
`go build` / `go mod download`:

| Requirement | Version | Purpose |
| --- | --- | --- |
| Go toolchain | `1.25` | To build the agent (build-time only) |
| github.com/miekg/pkcs11 | v1.1.1 | Talk to the USB token |
| fyne.io/systray | v1.11.0 | System-tray icon |
| github.com/zalando/go-keyring | v0.2.5 | OS keychain access |
| golang.org/x/sys | v0.44.0 | OS syscalls |

**Install / run:**

- **Windows:** extract `dsc_bridge/windows-package.zip`, run `start-dsc-bridge.bat`.
- **macOS / Linux:** `cd dsc_bridge && ./build.sh && ./build/dsc-bridge`

The agent serves a local HTTPS endpoint on `https://127.0.0.1:8765`.

---

## 3. Token PKCS#11 driver — **Manual (per machine)**

The vendor driver for the specific USB token. This is the one piece that can
NEVER be auto-installed — it ships from the token vendor.

| Token | Driver |
| --- | --- |
| HYP2003 (HyperSecu) | HyperSecu / Castle PKCS#11 driver |
| WD ProxKey | Watchdata ProxKey driver |
| ePass | Feitian ePass driver |

---

## 4. Frontend assets — bundled (no action)

No npm / `package.json`. PDF.js (`pdf.min.js`, `pdf.worker.min.js`) is vendored
in `e_sign/public/js/vendor/` and bundled by `bench build`.

---

## Install checklist

- [ ] **Server:** `bench install-app e_sign` (auto: Python deps + custom field)
- [ ] **Signer machine:** install + run the DSC Bridge agent
- [ ] **Signer machine:** install the token's PKCS#11 vendor driver
- [ ] Plug in the USB token and verify the agent detects it

> If only step 1 is done, the app installs cleanly but **cannot sign** — steps 2
> and 3 are required on every signer's machine.

See `docs/installation.md` for the full step-by-step guide.
