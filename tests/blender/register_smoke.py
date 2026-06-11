from __future__ import annotations

from pathlib import Path
import importlib
import sys


ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT.parent

if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

addon = importlib.import_module("IMEBridge")

try:
    addon.unregister()
except Exception:
    pass

addon.register()
addon.unregister()
print("IMEBridge register/unregister smoke passed")
