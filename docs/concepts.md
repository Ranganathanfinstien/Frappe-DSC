# Concepts & Doctypes

This page explains the data model and how the pieces fit together.

## The big picture

```
DSC Profile  ──┐
               ├──▶  DSC Signing Request  ──▶  signed PDF (File)
DSC Rule  ─────┤            ▲
               │            │
DSC Document Sign  ─────────┘
               │
DSC Signature Template  ──▶  stamp appearance
DSC Agent Registration  ──▶  pairs the bridge agent
DSC Audit Event         ──▶  records every action
```

A **DSC Signing Request** is the unit of work — one request signs one document. It is
created either by a **DSC Rule** (automatic) or a **DSC Document Sign** record
(ad-hoc), and it carries a `source_doctype` + `source_name` pointing back at the
document being signed.

## Doctypes

### DSC Settings (Single)

Global configuration: agent port, hash algorithm, location enforcement, trust store
bundle, retention windows. See [Settings](settings.md).

### DSC Profile

Represents one DSC token and its certificate. Holds the certificate fingerprint,
common name, expiry, and an **Allowed Users** child table — the list of users
permitted to sign with this profile. An empty list means unrestricted.

Child doctypes:

- **DSC Profile User** — one allowed-user row.
- **DSC Previous Certificate** — history of renewed certificates.
- **DSC Expiry Warning Day** — when to warn before certificate expiry.

### DSC Rule + DSC Rule Condition

A **DSC Rule** targets a doctype and says "when a document of this type is submitted
or changed, create a signing request." **DSC Rule Condition** rows add field-level
filters so only matching documents trigger the rule. See
[Signing Rules](signing-rules.md).

### DSC Signature Template + DSC Signature Field

A **DSC Signature Template** defines the visible signature stamp — what it shows
(signer name, designation, "digitally signed by" line, timestamp, reason, location)
and, via **DSC Signature Field** rows, where it appears on the page. See
[Signature Templates](signature-templates.md).

### DSC Signing Request

The lifecycle record for one signing operation. Key fields: `source_doctype`,
`source_name`, `profile`, `signature_template`, `status`, `hash_to_be_signed`,
`signed_file`, plus signer location and client metadata.

Status flow:

```
Pending ──▶ In Progress ──▶ Signed
                │
                ├──▶ Failed ──(retry)──▶ Pending
                └──▶ Cancelled
```

### DSC Document Sign

The ad-hoc signing doctype. A user uploads a PDF, places the signature box by
drag-and-drop, and saving the record auto-creates a **DSC Signing Request**. Its own
`status` mirrors the request's lifecycle. See [Sign a Document](document-sign.md).

### DSC Agent Registration

Pairs a desktop **bridge agent** to a user via a one-time pairing code. See
[Bridge Agent](bridge-agent.md).

### DSC Audit Event

An append-only audit-log entry. The signing engine writes events such as *Hash
Computed*, *Agent Called*, *Request Signed*, *PDF Verified*, *Request Failed*. See
[Audit & Reports](audit-and-reports.md).

## Key engine components

| Module | Responsibility |
|---|---|
| `api/signing.py` | Whitelisted endpoints: `initiate`, `finalize`, `retry`, `cancel`, status |
| `digital_signature/signing_engine.py` | Builds the PAdES PDF, computes the hash, verifies signatures |
| `digital_signature/rule_engine.py` | Evaluates DSC Rules on document events |
| `digital_signature/audit.py` | Writes DSC Audit Events |
| `digital_signature/print_gate.py` / `email_gate.py` | Block printing/emailing of unsigned documents |
| `digital_signature/permissions.py` | Role-based access for requests and profiles |

## How a signature is produced (PAdES)

1. The server renders the PDF — from a print format, or from the uploaded PDF for
   ad-hoc signing.
2. It builds the PAdES `SignedAttrs` and computes a hash.
3. The DSC token signs that hash.
4. The server embeds the signature into the PDF as a CMS structure, referencing the
   signer certificate via `signing-certificate-v2`.
5. The signed PDF is verified against the [trust store](trust-store.md).
</content>
