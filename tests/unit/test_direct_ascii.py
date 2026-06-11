import unittest

from tests.support.env import import_bridge_module, patched, reset_runtime
from tests.support.fakes import FakeWin, text_editor_target


class DirectAsciiTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.guards = import_bridge_module("bridge.ime_guards")
        self.insert_queue = import_bridge_module("targets.queue")
        self.runtime = import_bridge_module("core.runtime")
        self.win = FakeWin()
        self.hwnd = 456

    def test_direct_ascii_key_and_char_predicates_are_narrow(self) -> None:
        self.assertTrue(self.guards.is_direct_ascii_vkey(self.win, ord("A")))
        self.assertTrue(self.guards.is_direct_ascii_vkey(self.win, self.win.VK_OEM_102))
        self.assertTrue(self.guards.is_direct_ascii_vkey(self.win, self.win.VK_SPACE))
        self.assertFalse(self.guards.is_direct_ascii_vkey(self.win, self.win.VK_F2))
        self.assertTrue(self.guards.is_direct_ascii_char(ord("~")))
        self.assertFalse(self.guards.is_direct_ascii_char(0x0A))
        self.assertFalse(self.guards.is_direct_ascii_char(0x80))

    def test_caps_lock_direct_ascii_queues_only_the_translated_char(self) -> None:
        target = text_editor_target()
        self.runtime.state.active_target = target
        self.win.user32.key_state[self.win.VK_CAPITAL] = 0x0001
        queued: list[tuple[tuple[object, ...], dict[str, object]]] = []
        raw_event = {"vkey": ord("A"), "key_down": 1}

        def queue(*args: object, **kwargs: object) -> None:
            queued.append((args, kwargs))

        with patched(self.guards.targets, "is_usable_input_target", lambda item: item is target):
            with patched(self.guards.ime_switch, "is_open", lambda *_args: True):
                with patched(
                    self.guards.ime_switch,
                    "is_native_conversion_mode",
                    lambda *_args: True,
                ):
                    with patched(
                        self.guards.platform_api,
                        "read_raw_keyboard",
                        lambda *_args: raw_event,
                    ):
                        self.assertEqual(
                            self.guards.handle_direct_ascii_guard(
                                self.win,
                                self.hwnd,
                                self.win.WM_INPUT,
                                0,
                                1,
                                lambda *_args: "",
                            ),
                            0,
                        )

                    with patched(self.guards.insert_queue, "queue", queue):
                        self.assertEqual(
                            self.guards.handle_direct_ascii_guard(
                                self.win,
                                self.hwnd,
                                self.win.WM_CHAR,
                                ord("A"),
                                0,
                                lambda *_args: "",
                            ),
                            0,
                        )

                    self.assertEqual(
                        self.guards.handle_direct_ascii_guard(
                            self.win,
                            self.hwnd,
                            self.win.WM_KEYUP,
                            ord("A"),
                            0,
                            lambda *_args: "",
                        ),
                        0,
                    )

        self.assertEqual(queued[0][0][0], "A")
        self.assertIs(queued[0][0][1], target)
        self.assertEqual(queued[0][1]["source"], self.insert_queue.SOURCE_DIRECT_ASCII)
        self.assertFalse(self.guards.direct_ascii_state_is_active(self.hwnd))

    def test_direct_ascii_does_not_start_without_caps_lock(self) -> None:
        target = text_editor_target()
        self.runtime.state.active_target = target
        raw_event = {"vkey": ord("A"), "key_down": 1}
        with patched(self.guards.targets, "is_usable_input_target", lambda item: item is target):
            with patched(self.guards.ime_switch, "is_open", lambda *_args: True):
                with patched(
                    self.guards.platform_api,
                    "read_raw_keyboard",
                    lambda *_args: raw_event,
                ):
                    result = self.guards.handle_direct_ascii_guard(
                        self.win,
                        self.hwnd,
                        self.win.WM_INPUT,
                        0,
                        1,
                        lambda *_args: "",
                    )
        self.assertIsNone(result)
        self.assertFalse(self.guards.direct_ascii_state_is_active(self.hwnd))


if __name__ == "__main__":
    unittest.main()
