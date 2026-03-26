"""krach — graph-based live coding audio system."""

from importlib.metadata import version

from krach.mixer import Mixer, NodeHandle

__version__ = version("krach")

__all__ = ["Mixer", "NodeHandle", "__version__"]
