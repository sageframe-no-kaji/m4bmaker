# Releasing m4bmaker

## The sequence

1. **Build macOS** — run the build script locally, sign, notarize, test the DMG
2. **Publish to PyPI** — build the Python package and upload it
3. **Push the tag** — this automatically triggers the Windows build in GitHub Actions
4. **Download Windows artifact** — from the Actions run, test the installer
5. **Upload to Payhip** — upload macOS DMG and Windows installer
6. **Create GitHub Release** — this is what triggers the in-app update notification for existing users
7. **Close issues** — reference the release version in closing comments

> **The tag does not notify users.** Only the published GitHub Release does.
> Tag whenever it's convenient — it just kicks off the Windows CI.

---

## Before you start — version checklist

All five of these must be updated and committed before building anything:

| File | Field |
|------|-------|
| `m4bmaker/__init__.py` | `__version__` |
| `pyproject.toml` | `version` |
| `m4bmaker.spec` | `CFBundleShortVersionString` and `CFBundleVersion` |
| `installer.iss` | `AppVersion` |
| `CHANGELOG.md` | new `[x.y.z]` entry |

---

## Step 1 — macOS build

Requires: macOS, Xcode, Developer ID Application certificate, Apple notarization credentials in keychain.

```bash
export CODESIGN_IDENTITY="Developer ID Application: ANDREW TODD MARCUS (3N8F759K8D)"
export NOTARIZE_KEYCHAIN_PROFILE="<profile name stored in keychain>"

./scripts/build_macos.sh --dmg
```

Verify after the script finishes:
```bash
codesign --verify --deep --strict dist/m4bmaker.app
spctl --assess --type execute --verbose dist/m4bmaker.app
```

Open the DMG and test the app before moving on.

### Rules that must not change (learned the hard way during 1.0.1)

These are baked into `build_macos.sh` — do not modify the signing approach:

- **Never use `codesign --deep`** — it signs inner binaries in the wrong order and invalidates their signatures. The script signs inside-out: dylibs first, then frameworks deepest-first, then the bundle.
- **Use `ditto` for DMG staging, not `cp -r`** — `cp -r` follows symlinks and destroys `.framework` bundle structure, which breaks notarization.
- **Sign `.framework` directories as bundles** — not just the Mach-O binary inside them.
- **Notarize the DMG, not the app** — submit the `.dmg` file to notarytool.
- **Staple after notarization** — `xcrun stapler staple dist/<name>.dmg`.

---

## Step 2 — PyPI

```bash
python -m build
twine check dist/m4bmaker-<version>*
twine upload dist/m4bmaker-<version>*
```

Credentials are in keychain / `~/.pypirc`.

---

## Step 3 — Tag (triggers Windows CI automatically)

```bash
git push origin main
git tag v<version>
git push origin v<version>
```

Go to https://github.com/sageframe-no-kaji/m4bmaker/actions and watch the Windows build run. It takes a few minutes. When it finishes, download the artifact: `m4Bookmaker-windows-setup.zip`.

Test the installer on Windows before distributing.

> You can also trigger the Windows build manually from the Actions tab without a tag
> (workflow_dispatch). Useful for testing CI before you're ready to tag.

### Windows CI — do not change these

- Uses `actions/checkout@v4` and `actions/setup-python@v5` — `@v6` does not exist and will break the build
- `pip install -e .` is required in addition to requirements — without it pytest cannot import the package
- GUI tests are skipped via `--ignore=tests/gui` — no display available in CI

---

## Step 4 — Upload to Payhip

Upload the macOS DMG and Windows installer to Payhip manually.

---

## Step 5 — Create GitHub Release

Create the release at https://github.com/sageframe-no-kaji/m4bmaker/releases/new

- Tag: `v<version>` (already pushed)
- Title: `v<version>`
- Body: paste the `CHANGELOG.md` section for this version

**This is the step that triggers the in-app update notification for existing users.**

---

## Step 6 — Close issues

Close any tracking issues with a comment referencing the version and the GitHub Release.
