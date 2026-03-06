use crate::protocol::ClientMessage;

pub trait ControlInput: Send {
    /// # Errors
    /// Returns an error string if the control input cannot be started.
    fn start(&mut self) -> Result<(), String>;

    fn poll(&mut self) -> Vec<ClientMessage>;

    fn stop(&mut self);
}

/// Mock control input for testing — queues messages for `poll()`.
#[derive(Debug, Default)]
pub struct MockControlInput {
    queue: Vec<ClientMessage>,
}

impl MockControlInput {
    #[must_use]
    pub const fn new() -> Self {
        Self { queue: Vec::new() }
    }

    pub fn send(&mut self, msg: ClientMessage) {
        self.queue.push(msg);
    }
}

impl ControlInput for MockControlInput {
    fn start(&mut self) -> Result<(), String> {
        Ok(())
    }

    fn poll(&mut self) -> Vec<ClientMessage> {
        std::mem::take(&mut self.queue)
    }

    fn stop(&mut self) {
        self.queue.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mock_control_queues_and_drains() {
        let mut ctrl = MockControlInput::new();
        ctrl.send(ClientMessage::Ping);
        ctrl.send(ClientMessage::Shutdown);

        let msgs = ctrl.poll();
        assert_eq!(msgs.len(), 2);
        assert!(matches!(msgs[0], ClientMessage::Ping));
        assert!(matches!(msgs[1], ClientMessage::Shutdown));

        // Second poll returns empty
        assert!(ctrl.poll().is_empty());
    }

    #[test]
    fn mock_control_start_stop() {
        let mut ctrl = MockControlInput::new();
        assert!(ctrl.start().is_ok());
        ctrl.send(ClientMessage::Ping);
        ctrl.stop();
        assert!(ctrl.poll().is_empty());
    }
}
