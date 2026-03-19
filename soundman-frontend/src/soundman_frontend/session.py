import json
import socket
from dataclasses import dataclass, field
from types import TracebackType

from pythonosc import osc_packet
from pythonosc.udp_client import SimpleUDPClient

from soundman_frontend.ir import GraphIr


@dataclass
class SoundmanSession:
    host: str = "127.0.0.1"
    port: int = 9000
    _client: SimpleUDPClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = SimpleUDPClient(self.host, self.port)

    def load_graph(self, graph: GraphIr) -> None:
        self._client.send_message("/soundman/load_graph", graph.to_json())  # type: ignore[reportUnknownMemberType]

    def set(self, label: str, value: float) -> None:
        self._client.send_message("/soundman/set", [label, value])  # type: ignore[reportUnknownMemberType]

    def gain(self, value: float) -> None:
        self._client.send_message("/soundman/gain", value)  # type: ignore[reportUnknownMemberType]

    def ping(self) -> None:
        self._client.send_message("/soundman/ping", [])  # type: ignore[reportUnknownMemberType]

    def shutdown(self) -> None:
        self._client.send_message("/soundman/shutdown", [])  # type: ignore[reportUnknownMemberType]

    def list_nodes(self, timeout: float = 1.0) -> list[str]:
        """Query soundman for registered node type IDs.

        Sends /soundman/list_nodes <reply_port> and waits for a
        /soundman/node_types reply carrying a JSON-encoded list of type IDs.

        Raises TimeoutError if no reply arrives within `timeout` seconds.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reply_sock:
            reply_sock.bind(("127.0.0.1", 0))
            reply_sock.settimeout(timeout)
            _, reply_port = reply_sock.getsockname()
            self._client.send_message("/soundman/list_nodes", reply_port)  # type: ignore[reportUnknownMemberType]
            data, _ = reply_sock.recvfrom(4096)

        packet = osc_packet.OscPacket(data)
        msg = packet.messages[0].message
        return list[str](json.loads(msg.params[0]))

    def __enter__(self) -> "SoundmanSession":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass
