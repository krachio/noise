"""krach — graph-based live coding audio system."""

from importlib.metadata import version

from krach.mixer import Mixer, ModuleHandle, NodeHandle
from krach.module_proxy import SubModuleRef, module_decorator

__version__ = version("krach")

__all__ = ["Mixer", "ModuleHandle", "NodeHandle", "SubModuleRef", "module_decorator", "__version__"]
