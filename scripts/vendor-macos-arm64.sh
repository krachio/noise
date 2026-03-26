#!/usr/bin/env bash
# Vendor native dependencies into krach wheel layout (macOS ARM64).
# Run from repo root. Requires: brew install faust llvm, cargo.
set -euo pipefail

FAUST_PREFIX=$(brew --prefix faust)
LLVM_PREFIX=$(brew --prefix llvm)

BIN_DIR=krach/src/krach/_bin
LIB_DIR=krach/src/krach/_lib
SHARE_DIR=krach/src/krach/_share/faust

echo "Building krach-engine (release)..."
cargo build --release --bin krach-engine

echo "Copying binary..."
cp target/release/krach-engine "$BIN_DIR/"
chmod +x "$BIN_DIR/krach-engine"

echo "Copying libfaust..."
FAUST_REAL=$(readlink -f "$FAUST_PREFIX/lib/libfaust.2.dylib")
cp "$FAUST_REAL" "$LIB_DIR/libfaust.2.dylib"

echo "Copying libLLVM..."
cp "$LLVM_PREFIX/lib/libLLVM.dylib" "$LIB_DIR/libLLVM.dylib"

echo "Copying libunwind..."
UNWIND_LIB=$(otool -L target/release/krach-engine | grep libunwind | awk '{print $1}')
if [ -n "$UNWIND_LIB" ]; then
    UNWIND_REAL=$(readlink -f "$UNWIND_LIB")
    cp "$UNWIND_REAL" "$LIB_DIR/libunwind.1.dylib"
fi

echo "Copying FAUST stdlib..."
cp "$FAUST_PREFIX/share/faust/"*.lib "$SHARE_DIR/"

echo "Fixing rpaths..."
install_name_tool -change \
    "$FAUST_PREFIX/lib/libfaust.2.dylib" \
    "@loader_path/../_lib/libfaust.2.dylib" \
    "$BIN_DIR/krach-engine"

UNWIND_OLD=$(otool -L "$BIN_DIR/krach-engine" | grep libunwind | awk '{print $1}')
if [ -n "$UNWIND_OLD" ]; then
    install_name_tool -change \
        "$UNWIND_OLD" \
        "@loader_path/../_lib/libunwind.1.dylib" \
        "$BIN_DIR/krach-engine"
fi

install_name_tool -change \
    "$LLVM_PREFIX/lib/libLLVM.dylib" \
    "@loader_path/libLLVM.dylib" \
    "$LIB_DIR/libfaust.2.dylib"

install_name_tool -id "@rpath/libfaust.2.dylib" "$LIB_DIR/libfaust.2.dylib"

if [ -f "$LIB_DIR/libunwind.1.dylib" ]; then
    install_name_tool -id "@rpath/libunwind.1.dylib" "$LIB_DIR/libunwind.1.dylib"
fi

echo "Re-signing modified binaries..."
codesign --force --sign - "$BIN_DIR/krach-engine"
codesign --force --sign - "$LIB_DIR/libfaust.2.dylib"
[ -f "$LIB_DIR/libunwind.1.dylib" ] && codesign --force --sign - "$LIB_DIR/libunwind.1.dylib"

echo ""
echo "=== Vendored files ==="
du -sh "$BIN_DIR/" "$LIB_DIR/" "$SHARE_DIR/"
echo ""
echo "=== krach-engine deps ==="
otool -L "$BIN_DIR/krach-engine"
echo ""
echo "=== libfaust deps ==="
otool -L "$LIB_DIR/libfaust.2.dylib"
echo ""
echo "Done. Run: cd krach && uv run python -m hatchling build -t wheel"
