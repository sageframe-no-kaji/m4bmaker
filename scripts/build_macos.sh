#!/usr/bin/env bash
# build_macos.sh — build m4bmaker.app and (optionally) a distributable .dmg
#
# Usage:
#   ./scripts/build_macos.sh            # build .app
#   ./scripts/build_macos.sh --dmg      # build .app + .dmg
#   ./scripts/build_macos.sh --clean    # wipe build/ and dist/ only
#
# Prerequisites (in the active venv):
#   pip install pyinstaller
#
# System dependencies stay external (NOT bundled):
#   brew install ffmpeg
#
# For a signed + notarized release build, set:
#   export CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
#   export NOTARIZE_APPLE_ID="you@example.com"
#   export NOTARIZE_PASSWORD="@keychain:AC_PASSWORD"
#   export NOTARIZE_TEAM_ID="TEAMID"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

APP_NAME="m4bmaker"
SPEC_FILE="m4bmaker.spec"
VERSION="$(python -c "from m4bmaker import __version__; print(__version__)")"
DMG_NAME="${APP_NAME}-${VERSION}.dmg"

# ── Argument parsing ──────────────────────────────────────────────────────────
BUILD_DMG=false
CLEAN_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --dmg)   BUILD_DMG=true ;;
        --clean) CLEAN_ONLY=true ;;
    esac
done

# ── Clean ─────────────────────────────────────────────────────────────────────
echo "==> Cleaning build artefacts"
rm -rf build dist

if $CLEAN_ONLY; then
    echo "==> Clean done."
    exit 0
fi

# ── Preflight checks ──────────────────────────────────────────────────────────
echo "==> Checking environment"

if ! python -m PyInstaller --version &>/dev/null; then
    echo "ERROR: PyInstaller not found."
    echo "       Run: pip install pyinstaller"
    exit 1
fi

if ! command -v ffmpeg &>/dev/null; then
    echo "WARNING: ffmpeg not found on PATH — the final .app will require"
    echo "         the user to install ffmpeg separately (brew install ffmpeg)."
fi

# ── Build ─────────────────────────────────────────────────────────────────────
echo "==> Building ${APP_NAME}.app  (version ${VERSION})"
python -m PyInstaller "$SPEC_FILE" --noconfirm

APP_PATH="dist/${APP_NAME}.app"

if [[ ! -d "$APP_PATH" ]]; then
    echo "ERROR: Expected app bundle not found at $APP_PATH"
    exit 1
fi
echo "==> Built: $APP_PATH"

# ── Codesign ──────────────────────────────────────────────────────────────────
# PyInstaller ad-hoc signs the bundle during build. We must re-sign with our
# Developer ID, but --deep re-signs inner binaries in the wrong order and
# invalidates them. Instead we sign inside-out manually, then sign the bundle.
if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
    echo "==> Signing with identity: $CODESIGN_IDENTITY"
    ENTITLEMENTS="$SCRIPT_DIR/entitlements.plist"

    # 1. Sign all dylibs and .so files first (deepest layer)
    echo "    Signing dylibs..."
    find "$APP_PATH/Contents" \( -name "*.dylib" -o -name "*.so" \) | while read -r f; do
        codesign --force --options runtime \
            --entitlements "$ENTITLEMENTS" \
            --sign "$CODESIGN_IDENTITY" "$f"
    done

    # 2. Sign all .framework bundles inside-out (longest path = deepest = first).
    # PyInstaller copies the full Qt .framework directories; Apple requires the
    # bundle directory itself to be signed, not just the binary inside it.
    echo "    Signing framework bundles..."
    find "$APP_PATH/Contents" -name "*.framework" -type d | \
        awk '{ print length($0), $0 }' | sort -rn | awk '{print $2}' | \
        while read -r fw; do
            codesign --force --options runtime \
                --entitlements "$ENTITLEMENTS" \
                --sign "$CODESIGN_IDENTITY" "$fw"
        done

    # 3. Sign any loose Mach-O executables in Frameworks that are not
    # dylibs/so files and are not inside a .framework bundle.
    echo "    Signing loose framework executables..."
    find "$APP_PATH/Contents/Frameworks" -type f \
        ! -name "*.dylib" ! -name "*.so" ! -path "*.framework/*" | while read -r f; do
        file "$f" | grep -q "Mach-O" && \
            codesign --force --options runtime \
                --entitlements "$ENTITLEMENTS" \
                --sign "$CODESIGN_IDENTITY" "$f" || true
    done

    # 4. Sign executables in Contents/MacOS
    echo "    Signing main executables..."
    find "$APP_PATH/Contents/MacOS" -type f | while read -r f; do
        codesign --force --options runtime \
            --entitlements "$ENTITLEMENTS" \
            --sign "$CODESIGN_IDENTITY" "$f"
    done

    # 5. Sign the app bundle itself (no --deep)
    echo "    Signing app bundle..."
    codesign --force --options runtime \
        --entitlements "$ENTITLEMENTS" \
        --sign "$CODESIGN_IDENTITY" \
        "$APP_PATH"

    # 6. Verify
    codesign --verify --deep --strict "$APP_PATH" && echo "==> Signature verified OK"
else
    echo "==> Ad-hoc signing (local use only)"
    codesign --deep --force --sign - "$APP_PATH"
fi

# ── DMG ───────────────────────────────────────────────────────────────────────
if $BUILD_DMG; then
    echo "==> Creating $DMG_NAME"

    STAGING="$(mktemp -d)"
    # Use ditto (not cp -r) — cp -r follows symlinks, destroying .framework
    # bundle structure and invalidating code signatures.
    ditto "$APP_PATH" "$STAGING/$(basename "$APP_PATH")"
    ln -s /Applications "$STAGING/Applications"

    hdiutil create \
        -volname "$APP_NAME" \
        -srcfolder "$STAGING" \
        -ov -format UDZO \
        "dist/$DMG_NAME"

    rm -rf "$STAGING"
    echo "==> DMG: dist/$DMG_NAME"

    # ── Notarize (only if keychain profile or legacy env vars are set) ─────────
    if [[ -n "${NOTARIZE_KEYCHAIN_PROFILE:-}" ]]; then
        echo "==> Submitting for notarization (keychain profile: $NOTARIZE_KEYCHAIN_PROFILE)…"
        xcrun notarytool submit "dist/$DMG_NAME" \
            --keychain-profile "$NOTARIZE_KEYCHAIN_PROFILE" \
            --wait
        xcrun stapler staple "dist/$DMG_NAME"
        echo "==> Notarization complete."
    elif [[ -n "${NOTARIZE_APPLE_ID:-}" && -n "${NOTARIZE_PASSWORD:-}" && -n "${NOTARIZE_TEAM_ID:-}" ]]; then
        echo "==> Submitting for notarization…"
        xcrun notarytool submit "dist/$DMG_NAME" \
            --apple-id  "$NOTARIZE_APPLE_ID" \
            --password  "$NOTARIZE_PASSWORD" \
            --team-id   "$NOTARIZE_TEAM_ID" \
            --wait
        xcrun stapler staple "dist/$DMG_NAME"
        echo "==> Notarization complete."
    fi
fi

echo ""
echo "==> Done!  Output:"
ls -lh dist/
