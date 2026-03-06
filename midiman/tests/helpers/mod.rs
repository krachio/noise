use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use crossbeam_channel::Receiver;
use midiman::ipc;
use midiman::ipc::protocol::ServerMessage;
use midiman::scheduler::{self, SchedulerConfig, Slots, TimedEvent};

/// A running midiman kernel for integration tests.
///
/// Wires scheduler + IPC together with fast BPM for quick test cycles.
pub struct TestKernel {
    pub socket_path: PathBuf,
    pub slots: Slots,
    pub event_rx: Receiver<TimedEvent>,
    sched_handle: Option<scheduler::SchedulerHandle>,
    ipc_handle: Option<ipc::IpcHandle>,
}

impl TestKernel {
    /// Start a test kernel with 6000 BPM (1 cycle ≈ 40ms).
    pub fn start(suffix: &str) -> Self {
        let socket_path = std::env::temp_dir().join(format!(
            "midiman-tk-{}-{suffix}.sock",
            std::process::id()
        ));

        let (event_tx, event_rx) = crossbeam_channel::unbounded();

        let config = SchedulerConfig {
            bpm: 6000.0,
            beats_per_cycle: 4.0,
            lookahead_secs: 0.1,
            tick_interval_secs: 0.001,
        };

        let (sched_handle, slots) = scheduler::start(config, HashMap::new(), event_tx);
        let ipc_handle = ipc::start(socket_path.clone(), Arc::clone(&slots)).unwrap();

        Self {
            socket_path,
            slots,
            event_rx,
            sched_handle: Some(sched_handle),
            ipc_handle: Some(ipc_handle),
        }
    }

    /// Connect to the socket, send a JSON message, read the response.
    pub fn send(&self, json: &str) -> ServerMessage {
        let stream = UnixStream::connect(&self.socket_path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);

        writeln!(writer, "{json}").unwrap();
        let mut resp = String::new();
        reader.read_line(&mut resp).unwrap();
        serde_json::from_str(&resp).unwrap()
    }

    /// Open a persistent connection for sending multiple messages.
    pub fn connect(&self) -> TestConnection {
        let stream = UnixStream::connect(&self.socket_path).unwrap();
        let writer = stream.try_clone().unwrap();
        let reader = BufReader::new(stream);
        TestConnection { writer, reader }
    }

    /// Drain all events received so far.
    pub fn drain_events(&self) -> Vec<TimedEvent> {
        self.event_rx.try_iter().collect()
    }

    /// Wait for the given duration, then drain events.
    pub fn collect_events(&self, wait: Duration) -> Vec<TimedEvent> {
        std::thread::sleep(wait);
        self.drain_events()
    }

    /// Stop scheduler and IPC server.
    pub fn stop(mut self) {
        self.shutdown();
    }

    fn shutdown(&mut self) {
        if let Some(h) = self.ipc_handle.take() {
            h.stop();
        }
        if let Some(h) = self.sched_handle.take() {
            h.stop();
        }
    }
}

impl Drop for TestKernel {
    fn drop(&mut self) {
        self.shutdown();
    }
}

/// A persistent connection to a TestKernel for multi-message exchanges.
pub struct TestConnection {
    writer: UnixStream,
    reader: BufReader<UnixStream>,
}

impl TestConnection {
    pub fn send(&mut self, json: &str) -> ServerMessage {
        writeln!(self.writer, "{json}").unwrap();
        let mut resp = String::new();
        self.reader.read_line(&mut resp).unwrap();
        serde_json::from_str(&resp).unwrap()
    }
}
