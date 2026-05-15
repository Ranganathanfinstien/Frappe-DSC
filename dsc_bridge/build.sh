#!/bin/bash
# ============================================================
# Build script for dsc-bridge
# ============================================================
# Builds the Go binary for the current platform or cross-compiles
# for Windows / macOS. Optionally creates a Windows MSI installer.
#
# Usage:
#   ./build.sh                  # Build for current OS
#   ./build.sh windows          # Cross-compile for Windows x64 (needs mingw-w64)
#   ./build.sh windows-x86      # Cross-compile for Windows x86 (needs mingw-w64-i686)
#   ./build.sh darwin-amd64     # Build for macOS Intel (must run on a Mac)
#   ./build.sh darwin-arm64     # Build for macOS Apple Silicon (must run on a Mac)
#   ./build.sh darwin-universal # Build a universal Mac binary (must run on a Mac)
#   ./build.sh all              # Build everything possible on the current host
#   ./build.sh msi              # Build Windows MSI (requires go-msi + WiX)
#
# IMPORTANT — macOS:
#   Mac binaries must be built ON A MAC because the bridge links against
#   PKCS#11 via CGO and Apple does not legally redistribute its toolchain.
#   If you don't have a Mac, see the GitHub Actions workflow at
#   .github/workflows/build-bridge.yml — it builds all platforms in CI.
# ============================================================

set -e

APP_NAME="dsc-bridge"
VERSION="1.0.0"
BUILD_DIR="build"

mkdir -p "$BUILD_DIR"

build_local() {
    echo "Building $APP_NAME v$VERSION for $(go env GOOS)/$(go env GOARCH)..."
    go mod tidy
    go build -ldflags "-s -w" -o "$BUILD_DIR/$APP_NAME" .
    echo "Built: $BUILD_DIR/$APP_NAME"
}

build_windows_amd64() {
    echo "Cross-compiling $APP_NAME v$VERSION for windows/amd64..."
    if ! command -v x86_64-w64-mingw32-gcc &> /dev/null; then
        echo "ERROR: x86_64-w64-mingw32-gcc not found. Install with:"
        echo "  sudo apt install gcc-mingw-w64-x86-64    # Debian/Ubuntu"
        echo "  brew install mingw-w64                    # macOS (no PKCS#11 there anyway)"
        return 1
    fi
    go mod tidy
    GOOS=windows GOARCH=amd64 CGO_ENABLED=1 \
        CC=x86_64-w64-mingw32-gcc \
        go build -ldflags "-s -w -H windowsgui" -o "$BUILD_DIR/$APP_NAME.exe" .
    echo "Built: $BUILD_DIR/$APP_NAME.exe"
}

build_windows_x86() {
    echo "Cross-compiling $APP_NAME v$VERSION for windows/386..."
    if ! command -v i686-w64-mingw32-gcc &> /dev/null; then
        echo "ERROR: i686-w64-mingw32-gcc not found. Install with:"
        echo "  sudo apt install gcc-mingw-w64-i686       # Debian/Ubuntu"
        return 1
    fi
    go mod tidy
    GOOS=windows GOARCH=386 CGO_ENABLED=1 \
        CC=i686-w64-mingw32-gcc \
        go build -ldflags "-s -w -H windowsgui" -o "$BUILD_DIR/$APP_NAME-x86.exe" .
    echo "Built: $BUILD_DIR/$APP_NAME-x86.exe"
}

# darwin builds — only valid when running on a Mac. CGO + PKCS#11 means
# we need Apple's clang/SDK, which can't be cross-compiled cleanly from Linux.
build_darwin_amd64() {
    if [ "$(go env GOHOSTOS)" != "darwin" ]; then
        echo "ERROR: darwin-amd64 must be built on a Mac (CGO + PKCS#11 needs Apple's clang)."
        echo "       Use the GitHub Actions workflow instead — it has a macos-13 runner."
        return 1
    fi
    echo "Building $APP_NAME v$VERSION for darwin/amd64..."
    go mod tidy
    GOOS=darwin GOARCH=amd64 CGO_ENABLED=1 \
        go build -ldflags "-s -w" -o "$BUILD_DIR/$APP_NAME-darwin-amd64" .
    echo "Built: $BUILD_DIR/$APP_NAME-darwin-amd64"
}

build_darwin_arm64() {
    if [ "$(go env GOHOSTOS)" != "darwin" ]; then
        echo "ERROR: darwin-arm64 must be built on a Mac (Apple Silicon or Intel Mac)."
        echo "       Use the GitHub Actions workflow instead — it has a macos-14 runner."
        return 1
    fi
    echo "Building $APP_NAME v$VERSION for darwin/arm64..."
    go mod tidy
    GOOS=darwin GOARCH=arm64 CGO_ENABLED=1 \
        go build -ldflags "-s -w" -o "$BUILD_DIR/$APP_NAME-darwin-arm64" .
    echo "Built: $BUILD_DIR/$APP_NAME-darwin-arm64"
}

build_darwin_pkg() {
    # Wrap the universal binary into a proper .app bundle, then use Apple's
    # pkgbuild to produce a draggable .pkg installer that:
    #   - drops the .app into /Applications
    #   - runs `dsc-bridge --post-install` from the postinstall script
    # The .pkg requires macOS (pkgbuild is Mac-only). Without an Apple
    # Developer ID, signers see a one-time Gatekeeper warning on first launch
    # — System Settings > Privacy & Security > "Open Anyway".
    if [ "$(go env GOHOSTOS)" != "darwin" ]; then
        echo "ERROR: darwin-pkg must be built on a Mac (pkgbuild is Apple's tool)."
        echo "       Use the macOS GitHub Actions runner instead."
        return 1
    fi
    if ! command -v pkgbuild &> /dev/null; then
        echo "ERROR: pkgbuild not found. Install Xcode Command Line Tools:"
        echo "       xcode-select --install"
        return 1
    fi

    build_darwin_universal

    STAGE="$BUILD_DIR/macos-pkg-stage"
    APP="$STAGE/Applications/DSC Bridge.app"
    rm -rf "$STAGE"
    mkdir -p "$APP/Contents/MacOS"
    cp "$BUILD_DIR/$APP_NAME-darwin-universal" "$APP/Contents/MacOS/dsc-bridge"
    chmod +x "$APP/Contents/MacOS/dsc-bridge"

    cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>DSC Bridge</string>
    <key>CFBundleDisplayName</key><string>DSC Bridge</string>
    <key>CFBundleExecutable</key><string>dsc-bridge</string>
    <key>CFBundleIdentifier</key><string>com.esign.dsc-bridge</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>LSUIElement</key><true/>
    <key>LSMinimumSystemVersion</key><string>10.15</string>
</dict>
</plist>
EOF

    SCRIPTS="$BUILD_DIR/macos-pkg-scripts"
    rm -rf "$SCRIPTS"
    mkdir -p "$SCRIPTS"
    cat > "$SCRIPTS/postinstall" <<'EOF'
#!/bin/bash
set -e
"/Applications/DSC Bridge.app/Contents/MacOS/dsc-bridge" --post-install
exit 0
EOF
    chmod +x "$SCRIPTS/postinstall"

    cat > "$SCRIPTS/preremove" <<'EOF'
#!/bin/bash
"/Applications/DSC Bridge.app/Contents/MacOS/dsc-bridge" --pre-uninstall || true
pkill -f "DSC Bridge.app/Contents/MacOS/dsc-bridge" || true
exit 0
EOF
    chmod +x "$SCRIPTS/preremove"

    PKG="$BUILD_DIR/$APP_NAME-$VERSION.pkg"
    pkgbuild \
        --identifier com.esign.dsc-bridge \
        --version "$VERSION" \
        --root "$STAGE" \
        --scripts "$SCRIPTS" \
        --install-location / \
        "$PKG"
    echo "Built: $PKG"
    echo
    echo "NOTE: This .pkg is unsigned. Mac signers will see a one-time"
    echo "      'unidentified developer' warning. To allow it:"
    echo "      System Settings > Privacy & Security > 'Open Anyway'."
    echo "      To remove the warning, codesign with an Apple Developer ID."
}

build_darwin_universal() {
    # Produces a single fat binary that runs on both Intel and Apple Silicon.
    # Most user-friendly distribution format for Mac signers.
    if [ "$(go env GOHOSTOS)" != "darwin" ]; then
        echo "ERROR: darwin-universal must be built on a Mac."
        return 1
    fi
    if ! command -v lipo &> /dev/null; then
        echo "ERROR: lipo not found. It ships with Xcode Command Line Tools:"
        echo "       xcode-select --install"
        return 1
    fi
    build_darwin_amd64
    build_darwin_arm64
    echo "Combining into universal binary with lipo..."
    lipo -create \
        -output "$BUILD_DIR/$APP_NAME-darwin-universal" \
        "$BUILD_DIR/$APP_NAME-darwin-amd64" \
        "$BUILD_DIR/$APP_NAME-darwin-arm64"
    echo "Built: $BUILD_DIR/$APP_NAME-darwin-universal"
    echo
    echo "NOTE: Apple Gatekeeper will block unsigned binaries. To distribute:"
    echo "  1. Sign with: codesign --force --options=runtime --sign 'Developer ID Application: <Your Name>' $BUILD_DIR/$APP_NAME-darwin-universal"
    echo "  2. Notarise: xcrun notarytool submit ..."
    echo "  Or document the right-click → Open workaround for unsigned binaries."
}

build_all() {
    # Build everything that this host can produce.
    HOST_OS="$(go env GOHOSTOS)"
    if [ "$HOST_OS" = "linux" ]; then
        build_local
        build_windows_amd64 || true
        build_windows_x86 || true
        echo
        echo "Skipped: darwin-amd64, darwin-arm64 — must build on a Mac."
        echo "        Push to trigger .github/workflows/build-bridge.yml for those."
    elif [ "$HOST_OS" = "darwin" ]; then
        build_local
        build_darwin_universal
        echo
        echo "Skipped: windows builds — install mingw-w64 via brew if you need them."
    else
        build_local
    fi
}

case "${1:-local}" in
    local)              build_local ;;
    windows)            build_windows_amd64 ;;
    windows-x86)        build_windows_x86 ;;
    darwin-amd64)       build_darwin_amd64 ;;
    darwin-arm64)       build_darwin_arm64 ;;
    darwin-universal)   build_darwin_universal ;;
    darwin-pkg)         build_darwin_pkg ;;
    all)                build_all ;;

    msi)
        echo "Building Windows MSI installer..."
        if ! command -v go-msi &> /dev/null; then
            echo "ERROR: go-msi not found. Install with:"
            echo "  go install github.com/mh-cbon/go-msi@latest"
            exit 1
        fi
        GOOS=windows GOARCH=amd64 CGO_ENABLED=1 \
            CC=x86_64-w64-mingw32-gcc \
            go build -ldflags "-s -w -H windowsgui" -o "$BUILD_DIR/$APP_NAME.exe" .
        go-msi make --msi "$BUILD_DIR/$APP_NAME-$VERSION.msi" --version "$VERSION"
        echo "Built: $BUILD_DIR/$APP_NAME-$VERSION.msi"
        ;;

    test)
        echo "Running unit tests..."
        go mod tidy
        go test -v ./...
        ;;

    integration)
        echo "Running SoftHSM2 integration tests..."
        if [ ! -f /usr/lib/softhsm/libsofthsm2.so ]; then
            echo "ERROR: SoftHSM2 not installed. Run: sudo apt install softhsm2 opensc"
            exit 1
        fi
        echo "Tip: run ./test_setup.sh first if you haven't initialised the test token."
        go mod tidy
        go test -tags softhsm -v ./...
        ;;

    *)
        echo "Usage: ./build.sh [local|windows|windows-x86|darwin-amd64|darwin-arm64|darwin-universal|darwin-pkg|all|msi|test|integration]"
        exit 1
        ;;
esac
