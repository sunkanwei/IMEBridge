"""Select the native platform backend used by bridge code."""

import os
import sys

if os.name == "nt":
    from ..win32 import api as _backend
    _BACKEND_NAME = "windows"
elif sys.platform == "darwin":
    from . import macos as _backend
    _BACKEND_NAME = "macos"
else:
    from . import noop as _backend
    _BACKEND_NAME = "unsupported"


def backend_name() -> str:
    """Return the platform backend selected for this Blender session."""
    return _BACKEND_NAME


def supports_native_bridge() -> bool:
    """Whether this backend can install a real input bridge today."""
    return bool(getattr(_backend, "SUPPORTS_NATIVE_BRIDGE", False))


def ensure() -> object | None:
    """Create or return the selected backend's native API object."""
    return _backend.ensure()


def __getattr__(name: str) -> object:
    """Expose backend helpers without importing backend-specific modules directly."""
    return getattr(_backend, name)
