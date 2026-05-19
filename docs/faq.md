# FAQ & Troubleshooting

## General

### What kind of signature does this produce?

A **PAdES**-compliant PDF signature, built with [pyHanko]. It embeds the signer's
certificate chain and is verifiable in Adobe Acrobat and other PDF readers.

### Does the server ever see my token PIN or private key?

No. The PIN is entered locally in the [bridge agent](bridge-agent.md), and the private
key never leaves the DSC token. The server only ever receives the final signature
bytes.

### Do I need internet access to sign or verify?

No. The PDF viewer (`pdf.js`) is vendored into the app, and the trust store is built
in. Signing and verification work fully offline.

## Signing

### The "Sign with DSC" button does not appear

The button appears only when a **Pending** signing request exists for the document
and you are the expected signer. Confirm a [DSC Rule](signing-rules.md) fired, or that
a [DSC Document Sign](document-sign.md) record was saved with a PDF, profile and
placed signature box.

### "Could not reach the signing agent"

The [bridge agent](bridge-agent.md) is not running, or the port does not match
**DSC Settings → Agent listen port**. Start the agent and check the port.

### "Certificate mismatch"

The certificate on the plugged-in token does not match the one registered on the
**DSC Profile**. Make sure the correct token is connected, or update the profile.

### "Certificate expired"

The DSC Profile's certificate has passed its expiry date. Renew the certificate; the
app keeps renewal history in **DSC Previous Certificate** rows.

### "You are not authorised to sign with this profile"

The DSC Profile has an **Allowed Users** list and you are not on it. Ask the profile
owner to add you, or use a profile you are permitted to sign with.

## Document signing

### "Could not load the PDF viewer (pdf.js)"

The vendored pdf.js assets are missing. Run `bench build --app e_sign` and confirm
`e_sign/public/js/vendor/` contains `pdf.min.js` and `pdf.worker.min.js`.

### The signature box will not move

Placement is editable only while the record is in **Draft**. Once a signing request
exists, placement is locked.

## Verification & trust

### A signed PDF shows as untrusted

The signer's certificate does not chain to any CA in the [trust store](trust-store.md).
For an Indian DSC this should not happen — the CCA India bundle is built in. For other
CAs, upload the CA in **DSC Settings → Custom CA Trust Store Bundle**.

### Adobe shows trusted but the app does not (or vice versa)

They use different trust stores. Adobe checks its own trust list; the app checks
`cca_india_trust_bundle.pem` plus any custom bundle. "Trusted" is always relative to
the verifier.

## Administration

### How do I add a new CA to the trust store?

Upload a PEM bundle in **DSC Settings → Custom CA Trust Store Bundle**. See
[Trust Store](trust-store.md) for the full procedure.

### Where are failures reported?

In the **DSC Failure Reasons** report and the **DSC Audit Event** log. Some internal
errors are also written to the Frappe **Error Log**.

### How do I stop unsigned documents being printed or emailed?

The print and email gates are enabled through the app's hooks. When active, printing
or emailing a document that has not been signed is blocked.

[pyHanko]: https://github.com/MatthiasValvekens/pyHanko
</content>
