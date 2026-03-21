use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::time::Duration;

use midiman::engine::{Engine, EngineCommand, TimedEvent};
use midiman::ipc;
use midiman::ipc::protocol::ServerMessage;

/// A running midiman kernel for integration tests.
///
/// Wires Engine + IPC together with fast BPM (6000 BPM → 1 cycle ≈ 40ms).
/// The test thread manually drives the engine loop so tests are deterministic.
pub struct TestKernel {
    pub socket_path: PathBuf,
    cmd_rx: crossbeam_channel::Receiver<EngineCommand>,
    engine: Engine,
    ipc_handle: Option<ipc::IpcHandle>,
}

impl TestKernel {
    /// Start a test kernel with 6000 BPM (fast cycles for quick tests).
    pub fn start(suffix: &str) -> Self {
        let socket_path = std::env::temp_dir().join(format!(
            "midiman-tk-{}-{suffix}.sock",
            std::process::id()
        ));
        let (cmd_tx, cmd_rx) = crossbeam_channel::unbounded::<EngineCommand>();
        let engine = Engine::new(6000.0, 4.0, Duration::from_millis(200));
        let ipc_handle = ipc::start(socket_path.clone(), cmd_tx).unwrap();
        Self { socket_path, cmd_rx, engine, ipc_handle: Some(ipc_handle) }
    }

    /// Drain pending IPC commands into the engine, fill the heap, drain due events.
    pub fn tick(&mut self) -> Vec<TimedEvent> {
        while let Ok(cmd) = self.cmd_rx.try_recv() {
            self.engine.apply(cmd);
        }
        let now = std::time::Instant::now();
        self.engine.fill(now);
        self.engine.drain(now)
    }

    /// Poll the engine every 5ms for `wait`, collecting all due events.
    ///
    /// This mimics the real engine loop: ticking frequently ensures IPC commands
    /// are applied promptly and events are captured as soon as they become due.
    pub fn collect_events(&mut self, wait: Duration) -> Vec<TimedEvent> {
        let deadline = std::time::Instant::now() + wait;
        let mut collected = Vec::new();
        loop {
            collected.extend(self.tick());
            let now = std::time::Instant::now();
            if now >= deadline {
                break;
            }
            let remaining = deadline - now;
            std::thread::sleep(remaining.min(Duration::from_millis(5)));
        }
        collected
    }

    /// Tick once and return any immediately due events.
    pub fn drain_events(&mut self) -> Vec<TimedEvent> {
        self.tick()
    }

    /// Send a single JSON message and return the response.
    pub fn send(&self, json: &str) -> ServerMessage {
        let stream = UnixStream::connect(&self.socket_path).unwrap();
        let mut writer = stream.try_clone().unwrap();
        let mut reader = BufReader::new(stream);
        writeln!(writer, "{json}").unwrap();
        let mut resp = String::new();
        reader.read_line(&mut resp).unwrap();
        serde_json::from_str(&resp).unwrap()
    }

    /// Open a persistent connection for multiple messages.
    pub fn connect(&self) -> TestConnection {
        let stream = UnixStream::connect(&self.socket_path).unwrap();
        let writer = stream.try_clone().unwrap();
        let reader = BufReader::new(stream);
        TestConnection { writer, reader }
    }

    /// Resolve a slot index to its name.
    pub fn slot_name(&self, idx: usize) -> &str {
        self.engine.slot_name(idx)
    }

    pub fn stop(mut self) {
        if let Some(h) = self.ipc_handle.take() {
            h.stop();
        }
    }
}

impl Drop for TestKernel {
    fn drop(&mut self) {
        if let Some(h) = self.ipc_handle.take() {
            h.stop();
        }
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
