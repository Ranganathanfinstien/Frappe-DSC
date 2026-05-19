# Trust Store

The **trust store** is the set of Certificate Authorities (CAs) the app trusts when
**verifying** a signed PDF. It is what lets verification answer the question:
*"does this signature chain up to a CA we trust?"*

## Trust is not stored in the document

A signed PDF carries the signature, the signer's certificate chain, and a visible
stamp — but **not** a "trusted" verdict. Trust is decided **at verification time, by
the verifier**, relative to its trust store. The same PDF can verify as trusted on
one system and untrusted on another.

!!! warning "The visible stamp is not proof"
    The signature stamp drawn on the page is just an image. It appears regardless of
    whether the signature is valid. Only verification against a trust store proves
    trust.

## Two trust sources

`e_sign` builds its trusted-CA set by **merging two sources**:

| Source | What it is | Setup |
|---|---|---|
| **Built-in CCA India bundle** | `cca_india_trust_bundle.pem` shipped inside the app — every CCA India licensed CA | None — always on |
| **Custom CA bundle** | An optional PEM file uploaded in **DSC Settings → Custom CA Trust Store Bundle** | Admin uploads it |

The two are **additive** — an uploaded bundle is added *on top of* the built-in one,
never replacing it.

## Verifying a normal Indian DSC

No configuration needed. The built-in bundle already trusts all CCA India licensed
CAs (eMudhra, Capricorn, C-DAC, CDSL, CSC, and more), so genuine Indian DSC tokens
verify as trusted out of the box.

## Adding an extra CA

To trust a CA that is **not** a CCA India CA — for example a private or internal CA:

1. Obtain the CA certificate(s) in **PEM** format (text, with
   `-----BEGIN CERTIFICATE-----` blocks). To convert a binary `.cer`/`.der`:

    ```bash
    openssl x509 -inform der -in your_ca.cer -out your_ca.pem
    ```

   To add several CAs, concatenate the PEM blocks into one file.

2. Go to **DSC Settings → Custom CA Trust Store Bundle** and attach the `.pem` file.
3. Save.

The next verification trusts that CA in addition to all built-in CCA India CAs. No
restart is needed — the bundle is read fresh on each verification.

!!! note
    If an uploaded PEM is malformed it is ignored, and the failure is recorded in the
    **Error Log** under *"DSC trust store load failed"*. The built-in CAs still work.

## How verification decides "trusted"

When a signed PDF is verified, each signature yields four flags:

| Flag | Meaning |
|---|---|
| `intact` | The PDF has not been altered after signing |
| `valid` | The signature is cryptographically correct |
| `trusted` | The signer's certificate chains up to a CA in the trust store |
| `bottom_line` | Overall verdict — intact **and** valid **and** trusted |

A genuine Indian DSC → `trusted = True` from the built-in bundle. A self-signed or
unknown-CA certificate → `trusted = False`.

## Offline verification

Verification runs **fully offline** — it does not fetch CRL/OCSP or missing
intermediate certificates over the network. Any intermediate CA needed to complete a
chain must already be present in one of the bundles (the built-in CCA India bundle
covers Indian CA chains).
</content>
