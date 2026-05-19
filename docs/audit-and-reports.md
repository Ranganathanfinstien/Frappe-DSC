# Audit & Reports

`e_sign` records every signing action and provides analytics so administrators and
auditors can track activity, performance and failures.

## The audit trail

Every signing operation writes **DSC Audit Event** records — an append-only log tied
to a signing request. Typical events include:

| Event | Meaning |
|---|---|
| Signer Location Captured | The signer's geolocation was recorded |
| Hash Computed | The PAdES hash to be signed was prepared |
| Agent Called | Control was handed to the browser/agent for token signing |
| Request Signed | The signature was embedded and the PDF saved |
| PDF Verified | The signed PDF was verified after signing |
| Request Failed | Signing failed (with a reason) |
| Request Retried / Cancelled / Aborted | Lifecycle changes |

### Viewing the trail

- On a document, use **Digital Signature → View Signing History**.
- Or open the **DSC Audit Event** list directly.

Audit events are intended to be immutable evidence — do not edit or delete them.

## Reports

The app ships three reports under the **Digital signature** module:

### DSC Sign Volume

How many documents were signed over time — useful for tracking adoption and load.

### DSC Average Time to Sign

The average elapsed time from request creation to completed signature — a measure of
process efficiency and where signers get stuck.

### DSC Failure Reasons

A breakdown of why signing requests failed — surfaces recurring problems (token
issues, expired certificates, agent connectivity).

## Roles and visibility

| Role | Audit & report access |
|---|---|
| **DSC Administrator** | All requests, all events, all reports |
| **DSC Auditor** | Read-only access to requests and audit events |
| **DSC Signer** | Their own signing requests |

Visibility is enforced by permission hooks on **DSC Signing Request**, so signers see
only their own requests while auditors and administrators see everything.

## Tips

- Use **DSC Failure Reasons** regularly — a spike usually points to an expired
  certificate or an agent/token problem on a specific machine.
- The audit trail plus the signer-location capture provides legal evidence of *who*
  signed *what*, *when* and *where*.
</content>
