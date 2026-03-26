use std::env;
use std::process::Command;

fn main() {
    let faust_lib_dir = resolve_faust_lib_dir();
    let llvm_lib_dir = resolve_llvm_lib_dir();

    println!("cargo:rustc-link-search=native={faust_lib_dir}");
    println!("cargo:rustc-link-lib=dylib=faust");
    println!("cargo:rustc-link-search=native={llvm_lib_dir}");

    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-env-changed=FAUST_LIB_DIR");
    println!("cargo:rerun-if-env-changed=LLVM_LIB_DIR");
}

/// `FAUST_LIB_DIR` env → pkg-config → platform default
fn resolve_faust_lib_dir() -> String {
    if let Ok(dir) = env::var("FAUST_LIB_DIR") {
        return dir;
    }
    if let Some(dir) = pkg_config_lib_dir("faust") {
        return dir;
    }
    platform_faust_default()
}

/// `LLVM_LIB_DIR` env → `llvm-config --libdir` → platform default
fn resolve_llvm_lib_dir() -> String {
    if let Ok(dir) = env::var("LLVM_LIB_DIR") {
        return dir;
    }
    if let Some(dir) = llvm_config_libdir() {
        return dir;
    }
    platform_llvm_default()
}

fn pkg_config_lib_dir(name: &str) -> Option<String> {
    let output = Command::new("pkg-config")
        .args(["--variable=libdir", name])
        .output()
        .ok()?;
    if output.status.success() {
        let dir = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if !dir.is_empty() {
            return Some(dir);
        }
    }
    None
}

fn llvm_config_libdir() -> Option<String> {
    // Try llvm-config on PATH, then common homebrew locations
    let candidates = [
        "llvm-config",
        "/opt/homebrew/opt/llvm/bin/llvm-config",
        "/usr/local/opt/llvm/bin/llvm-config",
    ];
    for cmd in candidates {
        if let Ok(output) = Command::new(cmd).arg("--libdir").output()
            && output.status.success()
        {
            let dir = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if !dir.is_empty() {
                return Some(dir);
            }
        }
    }
    None
}

fn platform_faust_default() -> String {
    if cfg!(target_os = "macos") {
        if cfg!(target_arch = "aarch64") {
            "/opt/homebrew/lib".to_string()
        } else {
            "/usr/local/lib".to_string()
        }
    } else {
        "/usr/lib".to_string()
    }
}

fn platform_llvm_default() -> String {
    if cfg!(target_os = "macos") {
        if cfg!(target_arch = "aarch64") {
            "/opt/homebrew/opt/llvm/lib".to_string()
        } else {
            "/usr/local/opt/llvm/lib".to_string()
        }
    } else {
        "/usr/lib/llvm/lib".to_string()
    }
}
