import unittest

from tests.support.env import import_bridge_module, patched, reset_runtime
from tests.support.fakes import FakeWin, text_editor_target


class ImeConfirmSpaceTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.guards = import_bridge_module("bridge.ime_guards")
        self.runtime = import_bridge_module("core.runtime")
        self.win = FakeWin()
        self.hwnd = 123

    def test_space_event_kind_uses_raw_key_direction(self) -> None:
        with patched(
            self.guards.platform_api,
            "read_raw_keyboard",
            lambda _win, _lparam: {"vkey": self.win.VK_SPACE, "key_down": 1},
        ):
            self.assertEqual(
                self.guards.space_event_kind(self.win, self.win.WM_INPUT, 0, 9),
                self.guards.SPACE_EVENT_DOWN,
            )

        with patched(
            self.guards.platform_api,
            "read_raw_keyboard",
            lambda _win, _lparam: {"vkey": self.win.VK_SPACE, "key_down": 0},
        ):
            self.assertEqual(
                self.guards.space_event_kind(self.win, self.win.WM_INPUT, 0, 9),
                self.guards.SPACE_EVENT_UP,
            )

        self.assertEqual(
            self.guards.space_event_kind(
                self.win,
                self.win.WM_CHAR,
                self.win.VK_SPACE,
                0,
            ),
            self.guards.SPACE_EVENT_CHAR,
        )

    def test_confirm_space_sequence_is_owned_until_keyup(self) -> None:
        target = text_editor_target()
        self.runtime.state.composition_target = target

        def comp_reader(_win: object, _hwnd: object, _index: int) -> str:
            return "pin"

        with patched(self.guards.targets, "is_usable_input_target", lambda item: item is target):
            result = self.guards.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_KEYDOWN,
                self.win.VK_SPACE,
                0,
                comp_reader,
            )
            self.assertEqual(result, 0)
            self.assertTrue(self.guards.ime_confirm_space_is_active(self.hwnd))

            result = self.guards.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_CHAR,
                self.win.VK_SPACE,
                0,
                comp_reader,
            )
            self.assertEqual(result, 0)
            self.assertEqual(len(self.win.imm32.ui_messages), 2)

            result = self.guards.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_KEYUP,
                self.win.VK_SPACE,
                0,
                comp_reader,
            )
            self.assertEqual(result, 0)
            self.assertFalse(self.guards.ime_confirm_space_is_active(self.hwnd))

    def test_plain_space_without_composition_passes_through(self) -> None:
        with patched(self.guards.targets, "is_usable_input_target", lambda _item: False):
            result = self.guards.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_KEYDOWN,
                self.win.VK_SPACE,
                0,
                lambda *_args: "",
            )
        self.assertIsNone(result)
        self.assertFalse(self.guards.ime_confirm_space_is_active(self.hwnd))


if __name__ == "__main__":
    unittest.main()
