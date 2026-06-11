import unittest
from types import SimpleNamespace

from tests.support.env import import_bridge_module, patched


class RaisingTimers:
    def __init__(self, *, is_registered_error: Exception | None = None) -> None:
        self.is_registered_error = is_registered_error
        self.unregister_error: Exception | None = None
        self.unregister_called = False

    def is_registered(self, _callback: object) -> bool:
        if self.is_registered_error is not None:
            raise self.is_registered_error
        return True

    def unregister(self, _callback: object) -> None:
        self.unregister_called = True
        if self.unregister_error is not None:
            raise self.unregister_error


class SafeOpsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.safe_ops = import_bridge_module("core.safe_ops")

    def test_unregister_timer_swallows_stale_timer_lookup(self) -> None:
        timers = RaisingTimers(is_registered_error=ReferenceError("stale"))
        with patched(self.safe_ops.bpy, "app", SimpleNamespace(timers=timers)):
            self.assertFalse(self.safe_ops.unregister_timer(object()))

        self.assertFalse(timers.unregister_called)

    def test_unregister_timer_swallows_stale_unregister(self) -> None:
        timers = RaisingTimers()
        timers.unregister_error = AttributeError("gone")
        with patched(self.safe_ops.bpy, "app", SimpleNamespace(timers=timers)):
            self.assertFalse(self.safe_ops.unregister_timer(object()))

        self.assertTrue(timers.unregister_called)


if __name__ == "__main__":
    unittest.main()
