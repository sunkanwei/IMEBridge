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
        self.is_window_raises = False

    def IsWindow(self, hwnd: object) -> bool:
        if self.is_window_raises:
            raise OSError("IsWindow failed")
        return ptr_value(hwnd) in self.win.live_windows


class FakeHookWin:
    WM_NCDESTROY = 0x0082
    SUBCLASSPROC = ctypes.CFUNCTYPE(
        ctypes.c_ssize_t,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
    )

    def __init__(self, hwnd: int) -> None:
        self.live_windows = {hwnd}
        self.user32 = FakeHookUser32(self)
        self.default_result = 77
        self.def_calls: list[tuple[int, int]] = []
        self.remove_result = True
        self.remove_raises = False
        self.set_result = True
        self.set_raises = False
        self.subclasses: dict[tuple[int, int], object] = {}
        self.set_calls: list[tuple[int, int, int, int]] = []
        self.remove_calls: list[tuple[int, int, int]] = []

    def SetWindowSubclass(
        self,
        hwnd: object,
        callback: object,
        subclass_id: object,
        ref_data: object,
    ) -> int:
        if self.set_raises:
            raise OSError("SetWindowSubclass failed")
        if not self.set_result:
            return 0
        hwnd_value = ptr_value(hwnd)
        subclass_value = ptr_value(subclass_id)
        self.subclasses[(hwnd_value, subclass_value)] = callback
        callback_value = ptr_value(ctypes.cast(callback, ctypes.c_void_p))
        self.set_calls.append(
            (hwnd_value, callback_value, subclass_value, ptr_value(ref_data))
        )
        return 1

    def RemoveWindowSubclass(
        self,
        hwnd: object,
        callback: object,
        subclass_id: object,
    ) -> int:
        if self.remove_raises:
            raise OSError("RemoveWindowSubclass failed")
        hwnd_value = ptr_value(hwnd)
        subclass_value = ptr_value(subclass_id)
        callback_value = ptr_value(ctypes.cast(callback, ctypes.c_void_p))
        self.remove_calls.append((hwnd_value, callback_value, subclass_value))
        if not self.remove_result:
            return 0
        self.subclasses.pop((hwnd_value, subclass_value), None)
        return 1

    def DefSubclassProc(
        self,
        hwnd: object,
        msg: object,
        _wparam: object,
        _lparam: object,
    ) -> int:
        self.def_calls.append((ptr_value(hwnd), int(msg)))
        return self.default_result


class HookLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.hook = import_bridge_module("bridge.hook")
        self.ime_switch = import_bridge_module("bridge.ime_switch")
        self.runtime = import_bridge_module("core.runtime")
        self.hwnd = 700
        self.win = FakeHookWin(self.hwnd)
        self.item = {
            "hwnd": self.hwnd,
            "hwnd_value": self.hwnd,
            "visible": True,
            "class": "GHOST_WindowClass",
        }
        self.runtime.state.win = self.win

    def installed_callback(self) -> object:
        return self.win.subclasses[(self.hwnd, self.hook.SUBCLASS_ID)]

    def test_hook_window_installs_system_subclass(self) -> None:
        self.assertTrue(self.hook.hook_window(self.win, self.item))

        record = self.runtime.state.hooks[self.hwnd]
        self.assertIs(self.installed_callback(), record["callback"])
        self.assertEqual(len(self.win.set_calls), 1)
        self.assertTrue(record["control"]["active"])
        self.assertTrue(self.hook.has_active_hooks())

    def test_install_failure_does_not_store_callback(self) -> None:
        self.win.set_result = False

        self.assertFalse(self.hook.hook_window(self.win, self.item))

        self.assertEqual(self.runtime.state.hooks, {})
        self.assertEqual(self.win.subclasses, {})

    def test_install_exception_does_not_store_callback(self) -> None:
        self.win.set_raises = True

        self.assertFalse(self.hook.hook_window(self.win, self.item))

        self.assertEqual(self.runtime.state.hooks, {})
        self.assertEqual(self.win.subclasses, {})

    def test_cross_thread_window_is_not_subclassed(self) -> None:
        item = dict(self.item, current_thread=False)

        self.assertFalse(self.hook.hook_window(self.win, item))

        self.assertEqual(self.runtime.state.hooks, {})
        self.assertEqual(self.win.subclasses, {})

    def test_non_ghost_window_is_not_subclassed(self) -> None:
        item = dict(self.item, class_name="NotGhost")
        item["class"] = "NotGhost"

        self.assertFalse(self.hook.hook_window(self.win, item))

        self.assertEqual(self.runtime.state.hooks, {})
        self.assertEqual(self.win.subclasses, {})
        self.assertEqual(self.win.set_calls, [])

    def test_missing_handle_metadata_is_ignored(self) -> None:
        for item in (
            dict(self.item, hwnd=None),
            {"visible": True, "class": "GHOST_WindowClass"},
        ):
            with self.subTest(item=item):
                self.assertFalse(self.hook.hook_window(self.win, item))

        self.assertEqual(self.runtime.state.hooks, {})
        self.assertEqual(self.win.subclasses, {})
        self.assertEqual(self.win.set_calls, [])

    def test_start_hooks_reactivates_inactive_record_without_new_callback(self) -> None:
        self.assertTrue(self.hook.hook_window(self.win, self.item))
        record = self.runtime.state.hooks[self.hwnd]
        first_callback = record["callback"]
        record["control"]["active"] = False

        with patched(self.hook.platform_api, "ensure", lambda: self.win):
            with patched(
                self.hook.platform_api,
                "enum_process_windows",
                lambda include_children=True: [self.item],
            ):
                self.assertEqual(self.hook.start_hooks(insert_on_commit=True), 1)

        self.assertIs(self.runtime.state.hooks[self.hwnd]["callback"], first_callback)
        self.assertTrue(record["control"]["active"])
        self.assertEqual(len(self.win.set_calls), 2)

    def test_passthrough_uses_def_subclass_proc(self) -> None:
        self.assertTrue(self.hook.hook_window(self.win, self.item))

        with patched(
            self.hook.message_router,
            "handle_window_message",
            lambda *_args: import_bridge_module(
                "core.message_result"
            ).MessageResult.pass_through(),
        ):
            result = self.installed_callback()(
                self.hwnd,
                0x100,
                0,
                0,
                self.hook.SUBCLASS_ID,
                0,
            )

        self.assertEqual(result, 77)

        self.assertEqual(self.win.def_calls, [(self.hwnd, 0x100)])

    def test_handled_message_returns_router_value(self) -> None:
        self.assertTrue(self.hook.hook_window(self.win, self.item))
        message_result = import_bridge_module("core.message_result")

        with patched(
            self.hook.message_router,
            "handle_window_message",
            lambda *_args: message_result.MessageResult.handled_value(123),
        ):
            result = self.installed_callback()(
                self.hwnd,
                0x102,
                0,
                0,
                self.hook.SUBCLASS_ID,
                0,
            )

        self.assertEqual(result, 123)

        self.assertEqual(self.win.def_calls, [])

    def test_router_exception_falls_back_to_def_subclass_proc(self) -> None:
        self.assertTrue(self.hook.hook_window(self.win, self.item))

        def fail(*_args: object) -> None:
            raise RuntimeError("boom")

        with patched(self.hook.message_router, "handle_window_message", fail):
            result = self.installed_callback()(
                self.hwnd,
                0x102,
                0,
                0,
                self.hook.SUBCLASS_ID,
                0,
            )

        self.assertEqual(result, 77)

        self.assertEqual(self.win.def_calls, [(self.hwnd, 0x102)])

    def test_stop_hooks_removes_system_subclass(self) -> None:
        self.assertTrue(self.hook.hook_window(self.win, self.item))

        with patched(self.ime_switch, "restore_all_managed", lambda *_args: 0):
            self.assertEqual(self.hook.stop_hooks(), 1)

        self.assertEqual(self.runtime.state.hooks, {})
        self.assertEqual(self.win.subclasses, {})
        self.assertEqual(len(self.win.remove_calls), 1)

    def test_remove_failure_keeps_inactive_callback_alive(self) -> None:
        self.assertTrue(self.hook.hook_window(self.win, self.item))
        record = self.runtime.state.hooks[self.hwnd]
        self.win.remove_result = False

        with patched(self.ime_switch, "restore_all_managed", lambda *_args: 0):
            self.assertEqual(self.hook.stop_hooks(), 0)

        self.assertIs(self.runtime.state.hooks[self.hwnd], record)
        self.assertFalse(record["control"]["active"])
        self.assertFalse(self.hook.has_active_hooks())

        with patched(
            self.hook.message_router,
            "handle_window_message",
            lambda *_args: (_ for _ in ()).throw(
                AssertionError("inactive callback handled a message")
            ),
        ):
            result = self.installed_callback()(
                self.hwnd,
                0x102,
                0,
                0,
                self.hook.SUBCLASS_ID,
                0,
            )

        self.assertEqual(result, 77)

    def test_remove_exception_keeps_inactive_callback_alive(self) -> None:
        self.assertTrue(self.hook.hook_window(self.win, self.item))
        record = self.runtime.state.hooks[self.hwnd]
        self.win.remove_raises = True

        with patched(self.ime_switch, "restore_all_managed", lambda *_args: 0):
            self.assertEqual(self.hook.stop_hooks(), 0)

        self.assertIs(self.runtime.state.hooks[self.hwnd], record)
        self.assertFalse(record["control"]["active"])

    def test_is_window_exception_still_attempts_subclass_removal(self) -> None:
        self.assertTrue(self.hook.hook_window(self.win, self.item))
        self.win.user32.is_window_raises = True

        with patched(self.ime_switch, "restore_all_managed", lambda *_args: 0):
            self.assertEqual(self.hook.stop_hooks(), 1)

        self.assertEqual(self.runtime.state.hooks, {})
        self.assertEqual(len(self.win.remove_calls), 1)

    def test_destroyed_window_is_forgotten_on_stop(self) -> None:
        self.assertTrue(self.hook.hook_window(self.win, self.item))
        self.win.live_windows.clear()

        with patched(self.ime_switch, "restore_all_managed", lambda *_args: 0):
            self.assertEqual(self.hook.stop_hooks(), 1)

        self.assertEqual(self.runtime.state.hooks, {})
        self.assertEqual(self.win.remove_calls, [])

    def test_nc_destroy_removes_subclass_and_state(self) -> None:
        self.assertTrue(self.hook.hook_window(self.win, self.item))

        self.assertEqual(
            self.installed_callback()(
                self.hwnd,
                self.win.WM_NCDESTROY,
                0,
                0,
                self.hook.SUBCLASS_ID,
                0,
            ),
            77,
        )

        self.assertEqual(self.runtime.state.hooks, {})
        self.assertEqual(self.win.subclasses, {})
        self.assertEqual(self.win.def_calls, [(self.hwnd, self.win.WM_NCDESTROY)])

    def test_nc_destroy_remove_failure_keeps_inactive_callback_alive(self) -> None:
        self.assertTrue(self.hook.hook_window(self.win, self.item))
        record = self.runtime.state.hooks[self.hwnd]
        self.win.remove_result = False

        self.assertEqual(
            self.installed_callback()(
                self.hwnd,
                self.win.WM_NCDESTROY,
                0,
                0,
                self.hook.SUBCLASS_ID,
                0,
            ),
            77,
        )

        self.assertIs(self.runtime.state.hooks[self.hwnd], record)
        self.assertFalse(record["control"]["active"])
        self.assertIs(self.installed_callback(), record["callback"])

    def test_start_hooks_prunes_stale_inactive_records(self) -> None:
        self.runtime.state.hooks[self.hwnd] = {
            "hwnd": self.hwnd,
            "callback": object(),
            "control": {"active": False},
            "class": "GHOST_WindowClass",
        }
        self.win.live_windows.clear()

        with patched(self.hook.platform_api, "ensure", lambda: self.win):
            with patched(
                self.hook.platform_api,
                "enum_process_windows",
                lambda include_children=True: [],
            ):
                self.assertEqual(self.hook.start_hooks(insert_on_commit=True), 0)

        self.assertEqual(self.runtime.state.hooks, {})

    def test_auto_enable_retries_when_only_inactive_hooks_remain(self) -> None:
        window_hook = import_bridge_module("bridge.window_hook")
        self.runtime.state.hooks[self.hwnd] = {
            "hwnd": self.hwnd,
            "callback": object(),
            "control": {"active": False},
            "class": "GHOST_WindowClass",
        }
        self.runtime.state.auto_enable_timer_registered = True

        with patched(window_hook, "initialize_input_bridge", lambda *_args: (0, 0)):
            with patched(
                window_hook.platform_api,
                "supports_native_bridge",
                lambda: True,
            ):
                with patched(window_hook, "_macos_bridge_running", lambda: False):
                    result = window_hook._auto_enable_timer()

        self.assertEqual(result, window_hook.AUTO_ENABLE_RETRY_INTERVAL)
        self.assertTrue(self.runtime.state.auto_enable_timer_registered)
        self.assertEqual(self.runtime.state.auto_enable_attempts, 1)


if __name__ == "__main__":
    unittest.main()
