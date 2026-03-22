use std::fs;

use audio_engine::engine;
use audio_engine::engine::config::EngineConfig;
use audio_faust::loader;

fn tmp_dsp_dir() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    fs::write(
        dir.path().join("sine.dsp"),
        r#"
import("stdfaust.lib");
freq = hslider("freq", 440, 20, 20000, 1);
process = os.osc(freq);
"#,
    )
    .unwrap();
    fs::write(
        dir.path().join("gain.dsp"),
        r#"
gain = hslider("gain", 0.5, 0.0, 1.0, 0.01);
process = *(gain);
"#,
    )
    .unwrap();
    dir
}

#[test]
fn load_dsp_file_reads_code_and_derives_type_id() {
    let dir = tmp_dsp_dir();
    let (type_id, code) = loader::load_dsp_file(dir.path().join("sine.dsp"), dir.path()).unwrap();
    assert_eq!(type_id, "faust:sine");
    assert!(code.contains("process"));
}

#[test]
fn load_dsp_file_nonexistent_returns_error() {
    let result = loader::load_dsp_file("/nonexistent/path.dsp", "/nonexistent");
    assert!(result.is_err());
}

#[test]
fn register_dsp_dir_registers_all_dsp_files() {
    let dir = tmp_dsp_dir();
    let config = EngineConfig::default();
    let (mut ctrl, _proc) = engine::engine(&config);

    let registered =
        loader::register_dsp_dir(ctrl.registry_mut(), dir.path()).unwrap();

    assert_eq!(registered.len(), 2);
    assert!(registered.contains(&"faust:sine".to_string()));
    assert!(registered.contains(&"faust:gain".to_string()));

    // Verify they're actually in the registry
    assert!(ctrl.registry_mut().get_type("faust:sine").is_some());
    assert!(ctrl.registry_mut().get_type("faust:gain").is_some());
}

#[test]
fn register_dsp_dir_skips_non_dsp_files() {
    let dir = tmp_dsp_dir();
    fs::write(dir.path().join("readme.txt"), "not faust code").unwrap();

    let config = EngineConfig::default();
    let (mut ctrl, _proc) = engine::engine(&config);

    let registered =
        loader::register_dsp_dir(ctrl.registry_mut(), dir.path()).unwrap();

    assert_eq!(registered.len(), 2); // only .dsp files
}

#[test]
fn register_dsp_dir_reports_invalid_dsp() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(dir.path().join("bad.dsp"), "not valid faust!!!").unwrap();

    let config = EngineConfig::default();
    let (mut ctrl, _proc) = engine::engine(&config);

    let result = loader::register_dsp_dir(ctrl.registry_mut(), dir.path());
    assert!(result.is_err());
}
