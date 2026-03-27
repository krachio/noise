"""krach — graph-based live coding audio system."""

from importlib.metadata import version

from krach.mixer import Mixer, GraphHandle, NodeHandle
from krach.module_proxy import SubGraphRef, graph

__version__ = version("krach")

__all__ = ["Mixer", "GraphHandle", "NodeHandle", "SubGraphRef", "graph", "__version__"]
