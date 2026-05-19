# Sign a Document (DSC Document Sign)

**DSC Document Sign** is the ad-hoc signing feature: upload any PDF, place the
signature box exactly where you want it by drag-and-drop, and sign it with a DSC
token — without needing a rule or a print format.

## When to use it

Use DSC Document Sign for one-off or externally supplied PDFs. For routine documents
generated inside Frappe, use a [DSC Rule](signing-rules.md) instead.

## Step by step

### 1. Create the record

Open the **DSC Signing** workspace and click the **Sign a Document** shortcut (or
**DSC Document Sign → New**).

### 2. Fill the Document section

| Field | Description |
|---|---|
| **Title** | A name for this signing job |
| **PDF to Sign** | Upload the PDF you want to sign |
| **Signing Profile (DSC Token)** | The DSC Profile whose token will sign |
| **Signature Template** | Optional — controls the visible stamp content |

### 3. Place the signature

Scroll to the **Signature Placement** section. The uploaded PDF renders in the form.

- **Drag** the blue box to move the signature.
- **Drag the corner handle** to resize it.
- Use **Prev / Next** to change pages.

As you move the box, the read-only **Page**, **X**, **Y**, **Width** and **Height**
fields update automatically. Coordinates are stored in PDF points, origin at the
bottom-left.

!!! note
    The PDF viewer uses `pdf.js`, which is vendored into the app and served locally —
    placement works fully offline, no internet required.

### 4. Save

Saving a record that has a PDF, a profile and a placed box automatically:

- creates a **DSC Signing Request** (status **Pending**),
- locks the placement,
- changes the record status from **Draft** to **Pending**.

### 5. Sign

The **Sign with DSC** button now appears. Make sure the [bridge agent](bridge-agent.md)
is running and the token is plugged in, then click it and enter the token PIN.

### 6. Result

When signing completes:

- The record **status** becomes **Signed**.
- The **Signed PDF** field links to the signed file.
- An **Open Signed PDF** button appears on the form.

## Status lifecycle

The DSC Document Sign record mirrors its signing request:

```
Draft ──▶ Pending ──▶ In Progress ──▶ Signed
                            │
                            ├──▶ Failed ──(retry)──▶ Pending
                            └──▶ Cancelled
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "Could not load the PDF viewer (pdf.js)" | The vendored pdf.js assets are missing — run `bench build --app e_sign` and confirm `public/js/vendor/` is present |
| No draggable box appears | No PDF uploaded yet, or the record is already signed |
| "No signature position has been set" | Drag the box onto the page and save before signing |
| Placement is locked | A signing request already exists — placement is only editable while **Draft** |
</content>
