#!/usr/bin/env bash
# Vendor native dependencies into krach wheel layout (Linux x86_64).
# Run from repo root. Requires: cargo, patchelf, gh (GitHub CLI).
set -euo pipefail

BIN_DIR=krach/src/krach/_bin
LIB_DIR=krach/src/krach/_lib
SHARE_DIR=krach/src/krach/_share/faust

echo "Downloading libfaust (LLVM statically linked)..."
FAUST_VERSION=$(gh release view --repo grame-cncm/faust --json tagName -q .tagName)
gh release download --repo grame-cncm/faust -p "libfaust-ubuntu-x86_64.zip" -D /tmp --clobber
unzip -o /tmp/libfaust-ubuntu-x86_64.zip -d /tmp/faust-linux

echo "Downloading FAUST stdlib..."
gh release download --repo grame-cncm/faust -p "faust-${FAUST_VERSION}.tar.gz" -D /tmp --clobber
tar xzf "/tmp/faust-${FAUST_VERSION}.tar.gz" -C /tmp

echo "Building krach-engine (release)..."
FAUST_LIB_DIR=/tmp/faust-linux/lib cargo build --release --bin krach-engine

echo "Copying binary..."
cp target/release/krach-engine "$BIN_DIR/"
chmod +x "$BIN_DIR/krach-engine"

echo "Copying libfaust.so..."
cp /tmp/faust-linux/lib/libfaust.so "$LIB_DIR/libfaust.so"

echo "Copying FAUST stdlib..."
cp "/tmp/faust-${FAUST_VERSION}/libraries/"*.lib "$SHARE_DIR/"

echo "Fixing rpaths..."
patchelf --set-rpath '$ORIGIN/../_lib' "$BIN_DIR/krach-engine"
patchelf --set-soname libfaust.so "$LIB_DIR/libfaust.so"

echo ""
echo "=== Vendored files ==="
du -sh "$BIN_DIR/" "$LIB_DIR/" "$SHARE_DIR/"
echo ""
echo "=== krach-engine deps ==="
ldd "$BIN_DIR/krach-engine"
echo ""
echo "Done. Run: cd krach && uv run python -m hatchling build -t wheel"
