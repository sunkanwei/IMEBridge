import unittest

from tests.support.env import import_bridge_module, patched, reset_runtime


class FakeUser32:
    def __init__(self) -> None:
        self.process_ids = {100: 3000, 200: 3000, 900: 9999}
        self.thread_ids = {100: 11, 200: 22, 900: 99}
        self.classes = {
            100: "GHOST_WindowClass",
            200: "GHOST_WindowClass",
            900: "OtherProcessWindow",
        }

    def GetWindowThreadProcessId(self, hwnd: int, pid_ref: object) -> int:
        pid_ref._obj.value = self.process_ids[hwnd]
        return self.thread_ids[hwnd]

    def IsWindowVisible(self, _hwnd: int) -> bool:
        return True

    def GetClassNameW(self, hwnd: int, buffer: object, _length: int) -> int:
        buffer.value = self.classes[hwnd]
        return len(buffer.value)

    def EnumWindows(self, callback: object, _lparam: object) -> bool:
        callback(100, 0)
        callback(900, 0)
        return True

    def EnumChildWindows(
        self,
        parent: int,
        callback: object,
        _lparam: object,
    ) -> bool:
        if parent == 100:
            callback(200, 0)
        return True


class FakeKernel32:
    def GetCurrentThreadId(self) -> int:
        return 11


class FakeWin32Api:
    def __init__(self) -> None:
        self.user32 = FakeUser32()
        self.kernel32 = FakeKernel32()
        self.EnumWindowsProc = lambda callback: callback
        self.EnumChildProc = lambda callback: callback


class Win32ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.api = import_bridge_module("win32.api")
        self.win = FakeWin32Api()

    def test_enum_process_windows_marks_current_thread(self) -> None:
        with patched(self.api, "ensure_windows", lambda: self.win):
            with patched(self.api.os, "getpid", lambda: 3000):
                windows = self.api.enum_process_windows(include_children=True)

        self.assertEqual([item["hwnd_value"] for item in windows], [100, 200])
        self.assertEqual([item["thread_id"] for item in windows], [11, 22])
        self.assertEqual([item["current_thread"] for item in windows], [True, False])


if __name__ == "__main__":
    unittest.main()
