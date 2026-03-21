# Ralph Review Sprint 3

- [ ] STALE_SOCKET_DEFAULT — midiman-frontend/session.py:34 — default socket path is "/tmp/midiman.sock", should be "/tmp/noise-engine.sock". Env var name MIDIMAN_SOCKET should be NOISE_SOCKET.
- [ ] DOUBLE_SERIALIZE — midiman-frontend/session.py:155 — load_graph serializes GraphIr to JSON string then parses back to dict. Send the JSON string directly instead.
- [ ] DEAD_PACKAGE — soundman-frontend/ — entire directory still on disk, unused since krach dropped the dependency. Delete it.
