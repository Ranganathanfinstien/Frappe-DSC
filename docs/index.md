# Digital Signature (e_sign)

**`e_sign`** is a Digital Signature Certificate (DSC) signing platform for Frappe and
ERPNext. It lets users digitally sign PDF documents with a **physical DSC USB token**,
producing legally recognised, PAdES-compliant signatures.

## What it does

- Signs PDFs with a hardware **PKCS#11 DSC token** — the private key never leaves the
  device.
- Automates signing through a **Rules Engine**.
- Lets users **upload any PDF** and place a signature interactively.
- Verifies signatures against a **built-in CCA India trust store**.
- Records a complete **audit trail** of every signing action.

## The signing handshake

Signing is a three-way exchange. The server never sees the token PIN or private key —
only the final signature bytes.

```
Browser  ──▶  Frappe server   : "start signing this document"
Server   ──▶  Browser         : hash to be signed
Browser  ──▶  Bridge agent    : sign this hash on the token
Agent    ──▶  Browser         : signature bytes
Browser  ──▶  Frappe server   : here is the signature
Server                        : embed signature, verify, save
```

## Documentation map

| Page | What it covers |
|---|---|
| [Installation](installation.md) | Installing the app and the bridge agent |
| [Getting Started](getting-started.md) | First-time setup and your first signature |
| [Concepts & Doctypes](concepts.md) | The data model and how pieces fit together |
| [Bridge Agent](bridge-agent.md) | The desktop agent that talks to the DSC token |
| [Signing Rules](signing-rules.md) | Automating signing with DSC Rules |
| [Sign a Document](document-sign.md) | Ad-hoc upload-and-sign |
| [Signature Templates](signature-templates.md) | Designing the signature stamp |
| [Trust Store](trust-store.md) | How verification decides "trusted" |
| [Settings](settings.md) | DSC Settings reference |
| [Audit & Reports](audit-and-reports.md) | The audit log and analytics |
| [FAQ](faq.md) | Common questions and troubleshooting |

## Who should read what

- **Administrators** — start with [Installation](installation.md), then
  [Getting Started](getting-started.md), [Settings](settings.md) and
  [Trust Store](trust-store.md).
- **Signers** — read [Sign a Document](document-sign.md) and
  [Bridge Agent](bridge-agent.md).
- **Auditors** — read [Audit & Reports](audit-and-reports.md).
</content>
