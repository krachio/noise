from dataclasses import dataclass, field
from types import TracebackType

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

    def __enter__(self) -> "SoundmanSession":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass
