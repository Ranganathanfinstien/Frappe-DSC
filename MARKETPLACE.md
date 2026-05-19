# Frappe Marketplace Listing — Digital Signature (e_sign)

This file holds the copy and assets checklist for the **Frappe Marketplace**
listing. It is documentation only — it is not read by Frappe and does not affect
the app. Copy the relevant sections into the listing fields on your Frappe Cloud
developer dashboard when publishing.

---

## App identity

| Field | Value |
|---|---|
| App name | `e_sign` |
| App title | Digital Signature |
| Publisher | Ragav |
| Support email | prasathragav55@gmail.com |
| Category | Compliance / Document Management |
| Tags | digital signature, DSC, PAdES, e-sign, compliance, PDF, CCA India |

## Tagline (one line)

> Sign documents with a hardware DSC token — PAdES-compliant, audited, automated.

## Short description (≈ 50 words)

Digital Signature brings hardware DSC-token signing to Frappe and ERPNext. Sign any
PDF with a PKCS#11 USB token, automate signing with a rules engine, place signatures
visually, and verify every signature against a built-in CCA India trust store — with
a complete audit trail.

## Long description (Markdown — listing body)

```markdown
## Digital Signature for Frappe & ERPNext

Sign your business documents with a **physical DSC USB token**, the legally
recognised digital signature standard. The token's private key never leaves the
device — signing happens through a small local bridge agent, while the server builds
a standards-compliant **PAdES** signature around it.

### Why this app

- **Hardware-token signing** — PKCS#11 DSC tokens; the private key and PIN never
  reach the server.
- **PAdES-compliant** — signatures verify in Adobe Acrobat and other PDF readers.
- **Rules Engine** — auto-create signing requests when a document is submitted or
  changed; no manual step for routine documents.
- **Ad-hoc signing** — upload any PDF and place the signature box by drag-and-drop.
- **Visual signature designer** — control exactly where the stamp appears and what it
  shows.
- **Built-in CCA India trust store** — Indian DSC tokens verify as trusted out of the
  box; add your own CAs when needed.
- **Full audit trail** — every action logged, with optional signer geolocation.
- **Print & email gating** — stop unsigned documents from being printed or emailed.
- **Analytics** — sign volume, time-to-sign, and failure-reason reports.

### How it works

A three-way handshake between the browser, the Frappe server, and a local bridge
agent: the server prepares the PDF and a hash, the token signs the hash, and the
server embeds the signature and verifies it. Secure by design — the server only ever
sees the final signature bytes.

### Who it's for

Organisations in regulated industries, accounting and compliance teams, and any
Frappe/ERPNext user who must apply legally valid digital signatures to PDFs.
```

## Screenshots checklist

Capture these for the listing carousel (1280×800 recommended):

1. **DSC Document Sign** — the PDF with the draggable signature box placed.
2. **Sign with DSC** — the signing progress dialog mid-handshake.
3. **DSC Signature Template** — the visual signature designer.
4. **DSC Rule** — a rule configured to auto-sign a doctype.
5. **DSC Signing workspace** — the workspace with shortcuts and cards.
6. **Reports** — the sign-volume / time-to-sign report.
7. **A signed PDF** — opened in a reader showing the verified signature panel.

## Logo / icon

- App logo: square PNG, transparent background, ≥ 512×512.
- Place in `e_sign/public/images/` and reference from the listing.

## Compatibility

| Dependency | Version |
|---|---|
| Frappe Framework | v15+ |
| ERPNext | optional |
| Python | 3.10+ |

## Pre-submission checklist

- [ ] All source files committed (no untracked files the build needs —
      `cca_india_trust_bundle.pem`, the `dsc_document_sign` doctype, vendored
      `public/js/vendor/` pdf.js).
- [ ] `README.md` complete and accurate.
- [ ] `license.txt` present; license string in `pyproject.toml` / `hooks.py`
      matches `license.txt`. **Note:** confirm this — `hooks.py` currently declares
      `GPL-3.0` while `license.txt` contains the MIT license. Resolve before
      publishing.
- [ ] App installs cleanly with `bench get-app` + `bench install-app e_sign` on a
      fresh site.
- [ ] Screenshots and logo prepared.
- [ ] Support email and documentation URL set.
- [ ] Changelog / release notes written for the first version.

## Links to provide in the listing

- **Documentation:** link to the published `docs/` site (MkDocs) or the repo
  `docs/` folder.
- **Source / issues:** the Git repository URL.
- **Support:** prasathragav55@gmail.com
</content>
