# Getting Started

This walkthrough takes you from a fresh install to your first digital signature.

## Prerequisites

- The `e_sign` app installed (see [Installation](installation.md)).
- A DSC USB token plus its driver on the signer's machine.
- The [bridge agent](bridge-agent.md) installed on the signer's machine.

## Step 1 — Review DSC Settings

Open **DSC Signing** workspace → **DSC Settings**. Check:

- **Agent listen port** — the port the bridge agent uses (default `4645`).
- **Default hash algorithm** — `sha256` is recommended.
- **Enforce signer location** — when on, signers must share their browser location.
- **Custom CA Trust Store Bundle** — leave empty unless you need extra CAs (see
  [Trust Store](trust-store.md)).

See [Settings](settings.md) for the full reference.

## Step 2 — Create a DSC Profile

A **DSC Profile** represents one DSC token and its certificate.

1. Go to **DSC Profile → New**.
2. Give it a label, and register the certificate details.
3. Optionally fill the **Allowed Users** table — only those users may sign with this
   profile. Leave it empty for an unrestricted profile.
4. Save.

## Step 3 — Pair the bridge agent

1. Go to **DSC Agent Registration → New**.
2. Save, then click **Generate Pairing Code**.
3. Open the bridge agent on the signer's machine and enter the pairing code.
4. The agent is now paired to that user.

## Step 4 — Choose how documents get signed

There are two ways to start a signing request:

### Option A — Automatic (DSC Rule)

Create a **DSC Rule** so a doctype is signed automatically when submitted or changed.
See [Signing Rules](signing-rules.md).

### Option B — Ad-hoc (DSC Document Sign)

Upload any PDF and place the signature yourself. See
[Sign a Document](document-sign.md).

## Step 5 — Sign a document

1. Open the document (or the **DSC Document Sign** record).
2. Make sure the bridge agent is running and the DSC token is plugged in.
3. Click **Sign with DSC** (under the **Digital Signature** button group).
4. Enter the token PIN when prompted.
5. The signed PDF is generated, attached, and verified.

## Step 6 — Confirm the result

- The document's **DSC status** indicator turns green ("Signed").
- The signed PDF is available as an attached **File**.
- A **DSC Audit Event** trail records every step — see
  [Audit & Reports](audit-and-reports.md).

## Next steps

- Design the signature stamp: [Signature Templates](signature-templates.md)
- Understand trust verification: [Trust Store](trust-store.md)
- Learn the data model: [Concepts & Doctypes](concepts.md)
</content>
