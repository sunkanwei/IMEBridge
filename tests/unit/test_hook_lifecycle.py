import ctypes
import unittest

from tests.support.env import import_bridge_module, patched, reset_runtime


def ptr_value(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if hasattr(value, "value"):
        return int(value.value or 0)
    return int(value)


class FakeHookUser32:
    def __init__(self, win: object) -> None:
        self.win = win

    def IsWindow(self, hwnd: object) -> bool:
        return ptr_value(hwnd) in self.win.live_windows

    def CallWindowProcW(
        self,
        _old_proc: object,
        _hwnd: object,
        _msg: object,
        _wparam: object,
        _lparam: object,
    ) -> int:
        return 0


class FakeHookWin:
    GWL_WNDPROC = -4
    WNDPROC = ctypes.CFUNCTYPE(
        ctypes.c_ssize_t,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )

    def __init__(self, hwnd: int, original_proc: int) -> None:
        self.current_proc = original_proc
        self.live_windows = {hwnd}
        self.user32 = FakeHookUser32(self)
        self.set_calls: list[tuple[int, int]] = []

    def GetWindowLongPtrW(self, _hwnd: object, _index: int) -> int:
        return self.current_proc

    def SetWindowLongPtrW(self, _hwnd: object, _index: int, value: object) -> int:
        previous = self.current_proc
        self.current_proc = ptr_value(value)
        self.set_calls.append((previous, self.current_proc))
        return previous


@unittest.skipUnless(
    hasattr(ctypes, "set_last_error") and hasattr(ctypes, "get_last_error"),
    "Windows window-procedure hook lifecycle tests",
)
class HookLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.hook = import_bridge_module("bridge.hook")
        self.ime_switch = import_bridge_module("bridge.ime_switch")
        self.runtime = import_bridge_module("core.runtime")
        self.hwnd = 700
        self.original_proc = 1000
        self.third_party_proc = 2000
        self.win = FakeHookWin(self.hwnd, self.original_proc)
        self.item = {
            "hwnd": self.hwnd,
            "hwnd_value": self.hwnd,
            "visible": True,
            "class": "GHOST_WindowClass",
        }
        self.runtime.state.win = self.win

    def test_detached_hook_is_reused_without_stacking_on_reenable(self) -> None:
        self.assertTrue(self.hook.hook_window(self.win, self.item))
        first_callback = self.win.current_proc
        record = self.runtime.state.hooks[self.hwnd]

        self.win.current_proc = self.third_party_proc
        with patched(self.ime_switch, "restore_all_managed", lambda *_args: 0):
            self.assertEqual(self.hook.stop_hooks(), 0)

        self.assertEqual(self.runtime.state.hooks, {})
        self.assertEqual(self.runtime.state.detached_hooks, [record])
        self.assertFalse(record["control"]["active"])

        with patched(self.hook.platform_api, "ensure", lambda: self.win):
            with patched(
                self.hook.platform_api,
                "enum_process_windows",
                lambda include_children=True: [self.item],
            ):
                self.assertEqual(self.hook.start_hooks(insert_on_commit=True), 1)

        self.assertEqual(self.win.current_proc, self.third_party_proc)
        self.assertEqual(len(self.win.set_calls), 1)
        self.assertIs(self.runtime.state.hooks[self.hwnd], record)
        self.assertEqual(self.runtime.state.detached_hooks, [])
        self.assertTrue(record["control"]["active"])

        self.win.current_proc = first_callback
        with patched(self.ime_switch, "restore_all_managed", lambda *_args: 0):
            self.assertEqual(self.hook.stop_hooks(), 1)

        self.assertEqual(self.win.current_proc, self.original_proc)
        self.assertEqual(self.runtime.state.detached_hooks, [])

    def test_detached_hook_is_reactivated_when_it_returns_to_chain_top(self) -> None:
        self.assertTrue(self.hook.hook_window(self.win, self.item))
        first_callback = self.win.current_proc
        record = self.runtime.state.hooks[self.hwnd]

        self.win.current_proc = self.third_party_proc
        with patched(self.ime_switch, "restore_all_managed", lambda *_args: 0):
            self.assertEqual(self.hook.stop_hooks(), 0)

        self.win.current_proc = first_callback
        with patched(self.hook.platform_api, "ensure", lambda: self.win):
            with patched(
                self.hook.platform_api,
                "enum_process_windows",
                lambda include_children=True: [self.item],
            ):
                self.assertEqual(self.hook.start_hooks(insert_on_commit=True), 1)

        self.assertEqual(self.win.current_proc, first_callback)
        self.assertEqual(len(self.win.set_calls), 1)
        self.assertIs(self.runtime.state.hooks[self.hwnd], record)
        self.assertEqual(self.runtime.state.detached_hooks, [])

    def test_detached_hook_for_destroyed_window_is_forgotten(self) -> None:
        self.assertTrue(self.hook.hook_window(self.win, self.item))
        record = self.runtime.state.hooks[self.hwnd]

        self.win.current_proc = self.third_party_proc
        with patched(self.ime_switch, "restore_all_managed", lambda *_args: 0):
            self.assertEqual(self.hook.stop_hooks(), 0)

        self.win.live_windows.clear()
        self.assertEqual(self.hook.sweep_detached_hooks(self.win), 0)
        self.assertEqual(self.runtime.state.detached_hooks, [])


if __name__ == "__main__":
    unittest.main()
