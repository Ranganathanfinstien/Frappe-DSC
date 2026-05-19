# Signing Rules

The **Rules Engine** automates signing. Instead of starting a signing request by
hand, you define a **DSC Rule** that says: *"when a document of this type reaches a
certain state, create a signing request automatically."*

## When rules fire

The app listens to document events on **every** doctype:

| Event | When it fires |
|---|---|
| `on_submit` | A document is submitted |
| `on_update_after_submit` | A submitted document is changed |
| `on_change` | A document is created or modified |

For each event, the rule engine checks whether a **DSC Rule** exists for that
doctype. If none exists, nothing happens — the check is cheap, so there is no
per-doctype configuration overhead.

## Creating a DSC Rule

1. Go to **DSC Rule → New**.
2. **Document Type** — the doctype the rule applies to (e.g. *Sales Invoice*).
3. **Print Format** — optional; the print format rendered into the PDF to be signed.
   If blank, the doctype's default print format (or *Standard*) is used.
4. **Profile** — the DSC Profile whose token will sign.
5. **Signature Template** — optional; controls the visible stamp.
6. **Conditions** — optional **DSC Rule Condition** rows to filter which documents
   trigger the rule.
7. Save.

## Conditions

A **DSC Rule Condition** narrows a rule to documents matching field criteria — for
example, *only Sales Invoices where `grand_total` > 100000*. Add one or more
condition rows; all must match for the rule to fire.

## What happens when a rule fires

1. A **DSC Signing Request** is created with status **Pending**, linked to the source
   document via `source_doctype` + `source_name`.
2. The global client script shows a **Sign with DSC** button on that document.
3. The signer signs it — see [Getting Started](getting-started.md).

## Rules vs. ad-hoc signing

| | DSC Rule | DSC Document Sign |
|---|---|---|
| Input | A Frappe document rendered via print format | An uploaded PDF |
| Trigger | Automatic, on document event | Manual, by creating a record |
| Signature position | From the Signature Template | Placed interactively |
| Best for | Routine, repeatable documents | One-off / external PDFs |

For ad-hoc signing see [Sign a Document](document-sign.md).

## Tips

- Keep the print format stable — its layout determines where the signature stamp
  lands when driven by a Signature Template.
- Use conditions to avoid signing drafts or low-value documents.
- A document can have multiple signing requests over time (e.g. after a retry).
</content>
