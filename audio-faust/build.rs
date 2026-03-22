fn main() {
    // Link against libfaust (homebrew default location on macOS)
    println!("cargo:rustc-link-search=native=/opt/homebrew/lib");
    println!("cargo:rustc-link-lib=dylib=faust");

    // Also need LLVM (faust depends on it)
    println!("cargo:rustc-link-search=native=/opt/homebrew/opt/llvm/lib");

    // Re-run if libfaust changes
    println!("cargo:rerun-if-changed=build.rs");
}
