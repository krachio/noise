use std::fs;
use std::sync::mpsc;
use std::time::Duration;

use soundman_core::engine;
use soundman_core::engine::config::EngineConfig;
use soundman_faust::loader;
use soundman_faust::watcher::{DspWatcher, WatchEvent};

const SINE_DSP: &str = r#"
import("stdfaust.lib");
freq = hslider("freq", 440, 20, 20000, 1);
process = os.osc(freq);
"#;

const GAIN_DSP: &str = r#"
gain = hslider("gain", 0.5, 0.0, 1.0, 0.01);
process = *(gain);
"#;

#[test]
fn watcher_detects_new_file() {
    let dir = tempfile::tempdir().unwrap();
    let (tx, rx) = mpsc::channel();

    let _watcher = DspWatcher::new(dir.path(), tx).unwrap();

    // Give the watcher time to start
    std::thread::sleep(Duration::from_millis(100));

    // Write a new .dsp file
    fs::write(dir.path().join("sine.dsp"), SINE_DSP).unwrap();

    let event = rx.recv_timeout(Duration::from_secs(5)).unwrap();
    assert!(
        matches!(event, WatchEvent::Changed { ref type_id, .. } if type_id == "faust:sine"),
        "expected Changed event for faust:sine, got {event:?}"
    );
}

#[test]
fn watcher_detects_modified_file() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(dir.path().join("gain.dsp"), GAIN_DSP).unwrap();

    // Small delay so the modify is clearly after creation
    std::thread::sleep(Duration::from_millis(50));

    let (tx, rx) = mpsc::channel();
    let _watcher = DspWatcher::new(dir.path(), tx).unwrap();
    std::thread::sleep(Duration::from_millis(100));

    // Modify the file
    let modified = "gain = hslider(\"gain\", 0.8, 0.0, 1.0, 0.01);\nprocess = *(gain);\n";
    fs::write(dir.path().join("gain.dsp"), modified).unwrap();

    let event = rx.recv_timeout(Duration::from_secs(5)).unwrap();
    assert!(
        matches!(event, WatchEvent::Changed { ref type_id, .. } if type_id == "faust:gain"),
        "expected Changed event for faust:gain, got {event:?}"
    );
}

#[test]
fn watcher_ignores_non_dsp_files() {
    let dir = tempfile::tempdir().unwrap();
    let (tx, rx) = mpsc::channel();

    let _watcher = DspWatcher::new(dir.path(), tx).unwrap();
    std::thread::sleep(Duration::from_millis(100));

    fs::write(dir.path().join("notes.txt"), "not faust").unwrap();

    let result = rx.recv_timeout(Duration::from_secs(1));
    assert!(result.is_err(), "should not emit events for non-.dsp files");
}

#[test]
fn watcher_detects_removal() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(dir.path().join("sine.dsp"), SINE_DSP).unwrap();

    std::thread::sleep(Duration::from_millis(50));

    let (tx, rx) = mpsc::channel();
    let _watcher = DspWatcher::new(dir.path(), tx).unwrap();
    std::thread::sleep(Duration::from_millis(100));

    fs::remove_file(dir.path().join("sine.dsp")).unwrap();

    let event = rx.recv_timeout(Duration::from_secs(5)).unwrap();
    assert!(
        matches!(event, WatchEvent::Removed { ref type_id } if type_id == "faust:sine"),
        "expected Removed event for faust:sine, got {event:?}"
    );
}

#[test]
fn watcher_reload_reregisters_in_registry() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(dir.path().join("gain.dsp"), GAIN_DSP).unwrap();

    let config = EngineConfig::default();
    let (mut ctrl, _proc) = engine::engine(&config);

    // Initial registration
    loader::register_dsp_dir(ctrl.registry_mut(), dir.path()).unwrap();
    let decl = ctrl.registry_mut().get_type("faust:gain").unwrap();
    assert_eq!(decl.controls.len(), 1);
    assert!((decl.controls[0].default - 0.5).abs() < f32::EPSILON);

    // Simulate reload with different default
    let code = "gain = hslider(\"gain\", 0.8, 0.0, 1.0, 0.01);\nprocess = *(gain);\n".to_string();
    let factory = soundman_faust::factory::FaustFactory::new("gain", &code);
    let new_decl = factory.probe_type_decl("faust:gain").unwrap();
    ctrl.registry_mut()
        .reregister(new_decl, factory)
        .unwrap();

    let updated_decl = ctrl.registry_mut().get_type("faust:gain").unwrap();
    assert!((updated_decl.controls[0].default - 0.8).abs() < f32::EPSILON);
}
