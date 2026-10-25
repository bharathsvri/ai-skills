#!/bin/bash
# Builds Muesli.app.
#
# Prefers SwiftPM (`swift build`). If SwiftPM is broken — some Command Line
# Tools installs ship a mismatched llbuild/SDK — falls back to invoking swiftc
# directly, which works because Muesli has zero package dependencies.
set -euo pipefail
cd "$(dirname "$0")/.."

CONFIG="${1:-release}"
BIN=""

pick_sdk() {
  # Newest SDK the compiler actually understands; xcrun sometimes points at a
  # newer SDK than the installed compiler (mismatched CLT halves).
  local sdkdir="/Library/Developer/CommandLineTools/SDKs"
  for candidate in "$sdkdir/MacOSX.sdk" "$sdkdir"/MacOSX15*.sdk "$sdkdir"/MacOSX14*.sdk; do
    if [ -d "$candidate" ]; then
      echo "$candidate"
      return
    fi
  done
  xcrun --sdk macosx --show-sdk-path
}

if swift build -c "$CONFIG" 2>/dev/null; then
  BIN=".build/$CONFIG/Muesli"
else
  echo "SwiftPM unavailable — compiling with swiftc directly"
  SDK="$(pick_sdk)"
  echo "Using SDK: $SDK"
  mkdir -p build
  OPT="-O"
  [ "$CONFIG" = "debug" ] && OPT="-Onone"
  # shellcheck disable=SC2046
  SDKROOT="$SDK" swiftc \
    -parse-as-library \
    "$OPT" \
    -target arm64-apple-macosx14.0 \
    -o build/Muesli-bin \
    $(find Sources/Muesli -name '*.swift' | sort)
  BIN="build/Muesli-bin"
fi

APP="build/Muesli.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/Muesli"
cp Support/Info.plist "$APP/Contents/Info.plist"
if [ -f Support/AppIcon.icns ]; then
  cp Support/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
fi

# Ad-hoc signature: enough for local TCC (mic / screen recording) attribution.
/usr/bin/codesign --force --sign - --identifier app.muesli.Muesli "$APP" >/dev/null 2>&1

echo "Built $APP"
