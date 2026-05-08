# Releasing m4bmaker

Three release channels per version: macOS binary, Windows binary, Python package (PyPI).

**Tag last.** The git tag triggers the in-app update announcement. Push it only after both binaries are built, signed, and verified.

---

## Pre-release checklist

Update all version strings to the new version number:

| File | Field |
|------|-------|
| `m4bmaker/__init__.py` | `__version__` |
| `pyproject.toml` | `version` |
| `m4bmaker.spec` | `CFBundleShortVersionString`, `CFBundleVersion` |
| `installer.iss` | `AppVersion` |
| `CHANGELOG.md` | add `[x.y.z]` entry |

Commit all five changes together before building anything.

---

## macOS binary (local, manual)

Requires: macOS with Xcode, Developer ID Application certificate, Apple notarization credentials in keychain.

```bash
export CODESIGN_IDENTITY="Developer ID Application: ANDREW TODD MARCUS (3N8F759K8D)"
export NOTARIZE_KEYCHAIN_PROFILE="<profile name from keychain>"

./scripts/build_macos.sh --dmg
```

Verify signature and notarization:
```bash
codesign --verify --deep --strict dist/m4bmaker.app
spctl --assess --type execute --verbose dist/m4bmaker.app
```

**Test the DMG before distributing.** Open on both Apple Silicon and Intel if possible.

### Critical signing rules (learned during 1.0.1 — do not change)

1. **Never use `codesign --deep`** — signs in wrong order, invalidates framework signatures. The script does it correctly: inside-out, dylibs first, then frameworks deepest-first, then bundle.
2. **Use `ditto` for DMG staging, not `cp -r`** — `cp -r` follows symlinks and destroys `.framework` structure, breaking CodeResources manifests.
3. **Sign `.framework` directories as bundles** — not just the Mach-O binary inside.
4. **Notarize the DMG, not the app** — submit `dist/<name>.dmg` to notarytool.
5. **Staple after notarization** — `xcrun stapler staple dist/<name>.dmg`.

---

## PyPI package (local, manual)

```bash
python -m build
twine check dist/m4bmaker-<version>*
twine upload dist/m4bmaker-<version>*
```

PyPI credentials are in keychain / `~/.pypirc`.

---

## Windows binary (GitHub Actions, automated)

Triggered by pushing a `v*` tag. Push the tag only after the macOS DMG is verified.

```bash
git push origin main
git tag v<version>
git push origin v<version>
```

Monitor the run at: https://github.com/sageframe-no-kaji/m4bmaker/actions

Download artifact `m4Bookmaker-windows-setup.zip` from the completed run. Test the installer before distributing.

### CI notes (do not change these)

- Uses `actions/checkout@v4` and `actions/setup-python@v5` — do NOT upgrade to `@v6` (doesn't exist)
- `pip install -e .` is required in addition to requirements so pytest can import the package
- GUI tests are skipped via `--ignore=tests/gui` — no display in CI

---

## Distribution

1. Upload macOS DMG to Payhip
2. Upload Windows installer to Payhip
3. Create GitHub Release `v<version>` — use the `CHANGELOG.md` section as release notes

---

## Post-release

- Close any tracking issues referencing this version
- Keep the GitHub Release open for user feedback on platform-specific issues
