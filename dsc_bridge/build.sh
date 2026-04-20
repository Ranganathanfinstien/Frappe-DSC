#!/bin/bash
# ============================================================
# Build script for dsc-bridge
# ============================================================
# Builds the Go binary for the current platform or cross-compiles
# for Windows. Optionally creates a Windows MSI installer.
#
# Usage:
#   ./build.sh                  # Build for current OS
#   ./build.sh windows          # Cross-compile for Windows
#   ./build.sh msi              # Build Windows MSI (requires go-msi + WiX)
# ============================================================

set -e

APP_NAME="dsc-bridge"
VERSION="1.0.0"
BUILD_DIR="build"

mkdir -p "$BUILD_DIR"

case "${1:-local}" in
    local)
        echo "Building $APP_NAME v$VERSION for $(go env GOOS)/$(go env GOARCH)..."
        go mod tidy
        go build -ldflags "-s -w" -o "$BUILD_DIR/$APP_NAME" .
        echo "Built: $BUILD_DIR/$APP_NAME"
        ;;

    windows)
        echo "Cross-compiling $APP_NAME v$VERSION for windows/amd64..."
        go mod tidy
        GOOS=windows GOARCH=amd64 CGO_ENABLED=1 \
            CC=x86_64-w64-mingw32-gcc \
            go build -ldflags "-s -w -H windowsgui" -o "$BUILD_DIR/$APP_NAME.exe" .
        echo "Built: $BUILD_DIR/$APP_NAME.exe"
        ;;

    msi)
        echo "Building Windows MSI installer..."

        if ! command -v go-msi &> /dev/null; then
            echo "ERROR: go-msi not found. Install with:"
            echo "  go install github.com/mh-cbon/go-msi@latest"
            exit 1
        fi

        # Build Windows binary first
        GOOS=windows GOARCH=amd64 CGO_ENABLED=1 \
            CC=x86_64-w64-mingw32-gcc \
            go build -ldflags "-s -w -H windowsgui" -o "$BUILD_DIR/$APP_NAME.exe" .

        # Generate MSI
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
        echo "Usage: ./build.sh [local|windows|msi|test|integration]"
        exit 1
        ;;
esac
