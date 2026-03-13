#!/usr/bin/env bash
# sign_and_notarize.sh — sign, notarize, staple m4bmaker.app + DMG
# Usage: ./scripts/sign_and_notarize.sh
# Requires: APPLE_ID and NOTARY_PASSWORD env vars (or edit below)
set -euo pipefail

IDENTITY="Developer ID Application: ANDREW TODD MARCUS (3N8F759K8D)"
TEAM_ID="3N8F759K8D"
BUNDLE_ID="com.sageframe.m4bmaker"
APP="dist/m4bmaker.app"
DMG="dist/m4Bookmaker-1.0-mac.dmg"

# Read credentials from env or prompt
APPLE_ID="${APPLE_ID:-}"
NOTARY_PASSWORD="${NOTARY_PASSWORD:-}"

if [[ -z "$APPLE_ID" ]]; then
  read -rp "Apple ID (email): " APPLE_ID
fi
if [[ -z "$NOTARY_PASSWORD" ]]; then
  read -rsp "App-specific password: " NOTARY_PASSWORD
  echo
fi

echo "==> 1. Signing $APP ..."
codesign --deep --force --options runtime \
  --entitlements scripts/entitlements.plist \
  --sign "$IDENTITY" \
  "$APP"

echo "==> 2. Verifying signature ..."
codesign --verify --deep --strict --verbose=2 "$APP"
spctl --assess --type execute --verbose "$APP" 2>&1 || true  # will fail pre-notarize, that's ok

echo "==> 3. Zipping for notarization ..."
rm -f /tmp/m4bmaker-notarize.zip
ditto -c -k --keepParent "$APP" /tmp/m4bmaker-notarize.zip

echo "==> 4. Submitting to Apple Notary (this takes 1-5 min) ..."
xcrun notarytool submit /tmp/m4bmaker-notarize.zip \
  --apple-id "$APPLE_ID" \
  --team-id "$TEAM_ID" \
  --password "$NOTARY_PASSWORD" \
  --wait

echo "==> 5. Stapling notarization ticket to app ..."
xcrun stapler staple "$APP"

echo "==> 6. Rebuilding DMG from stapled app ..."
rm -f "$DMG"
create-dmg \
  --volname "m4Bookmaker" \
  --volicon "m4bmaker/gui/resources/audiobookbinder.icns" \
  --background "dist/dmg-background.png" \
  --window-pos 200 120 \
  --window-size 600 400 \
  --icon-size 100 \
  --icon "m4bmaker.app" 175 200 \
  --hide-extension "m4bmaker.app" \
  --app-drop-link 425 200 \
  "$DMG" \
  "$APP"

echo "==> 7. Notarizing DMG ..."
xcrun notarytool submit "$DMG" \
  --apple-id "$APPLE_ID" \
  --team-id "$TEAM_ID" \
  --password "$NOTARY_PASSWORD" \
  --wait

echo "==> 8. Stapling ticket to DMG ..."
xcrun stapler staple "$DMG"

echo ""
echo "✓ Done! $DMG is signed, notarized, and stapled."
ls -lh "$DMG"
