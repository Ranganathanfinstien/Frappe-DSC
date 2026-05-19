# Installation

Installing `e_sign` has two parts: the **Frappe app** (server side) and the
**bridge agent** (on each signer's workstation).

## Requirements

- Frappe Framework v15+ (ERPNext optional)
- Python 3.10+
- A PKCS#11-compatible DSC USB token plus its vendor driver, on each signer's machine
- The bridge agent (Windows or macOS) on each signer's machine

Python dependencies (`pyhanko[image-support]`, `asn1crypto`) are installed
automatically by bench from `pyproject.toml`.

## Install the Frappe app

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app e_sign
```

### What installation does

- Runs the `after_install` hook, which adds an `is_dsc_signed` **Custom Field** to the
  core **File** doctype (used to mark and protect signed PDFs).
- Ships three roles as fixtures: `DSC Administrator`, `DSC Signer`, `DSC Auditor`.
- Registers the **DSC Signing** workspace.

### Verify the install

```bash
bench --site $YOUR_SITE list-apps        # e_sign should appear
```

Then open the Desk and confirm the **DSC Signing** workspace is visible.

## Install the bridge agent

Each signer needs the bridge agent on their machine — it is what physically talks to
the DSC token. See [Bridge Agent](bridge-agent.md) for details. In short:

1. Download the installer for the signer's OS (Windows or macOS).
2. Run the installer.
3. The agent runs in the background and listens on `https://127.0.0.1:<port>`.

## Build assets (if needed)

Static assets are served from the app's `public/` folder. If you edit or add assets:

```bash
bench build --app e_sign
```

!!! note
    The app vendors `pdf.js` under `e_sign/public/js/vendor/` so the document
    signature placement viewer works fully offline. No internet access is required at
    runtime.

## Upgrading

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app --branch develop e_sign        # pulls latest
bench --site $YOUR_SITE migrate
bench build --app e_sign
```

## Uninstall

```bash
bench --site $YOUR_SITE uninstall-app e_sign
```
</content>
