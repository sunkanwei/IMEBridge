import unittest

from tests.support.env import import_bridge_module, patched, reset_runtime
from tests.support.fakes import FakeWin, font_target, text_editor_target


class ImeConfirmSpaceTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.common = import_bridge_module("bridge.ime_guard_common")
        self.confirm_space = import_bridge_module("bridge.ime_confirm_space")
        self.runtime = import_bridge_module("core.runtime")
        self.win = FakeWin()
        self.hwnd = 123

    def test_space_event_kind_uses_raw_key_direction(self) -> None:
        with patched(
            self.confirm_space.platform_api,
            "read_raw_keyboard",
            lambda _win, _lparam: {"vkey": self.win.VK_SPACE, "key_down": 1},
        ):
            self.assertEqual(
                self.confirm_space.space_event_kind(self.win, self.win.WM_INPUT, 0, 9),
                self.confirm_space.SPACE_EVENT_DOWN,
            )

        with patched(
            self.confirm_space.platform_api,
            "read_raw_keyboard",
            lambda _win, _lparam: {"vkey": self.win.VK_SPACE, "key_down": 0},
        ):
            self.assertEqual(
                self.confirm_space.space_event_kind(self.win, self.win.WM_INPUT, 0, 9),
                self.confirm_space.SPACE_EVENT_UP,
            )

        self.assertEqual(
            self.confirm_space.space_event_kind(
                self.win,
                self.win.WM_CHAR,
                self.win.VK_SPACE,
                0,
            ),
            self.confirm_space.SPACE_EVENT_CHAR,
        )

    def test_confirm_space_sequence_is_owned_until_keyup(self) -> None:
        target = text_editor_target()
        self.runtime.state.composition_target = target

        def comp_reader(_win: object, _hwnd: object, _index: int) -> str:
            return "pin"

        with patched(
            self.common.targets,
            "is_usable_input_target",
            lambda item: item is target,
        ):
            result = self.confirm_space.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_KEYDOWN,
                self.win.VK_SPACE,
                0,
                comp_reader,
            )
            self.assertEqual(result, 0)
            self.assertTrue(self.confirm_space.ime_confirm_space_is_active(self.hwnd))

            result = self.confirm_space.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_CHAR,
                self.win.VK_SPACE,
                0,
                comp_reader,
            )
            self.assertEqual(result, 0)
            self.assertEqual(len(self.win.imm32.ui_messages), 2)

            result = self.confirm_space.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_KEYUP,
                self.win.VK_SPACE,
                0,
                comp_reader,
            )
            self.assertEqual(result, 0)
            self.assertFalse(self.confirm_space.ime_confirm_space_is_active(self.hwnd))

    def test_confirm_space_swallow_late_char_after_keyup(self) -> None:
        target = text_editor_target()
        self.runtime.state.composition_target = target

        def comp_reader(_win: object, _hwnd: object, _index: int) -> str:
            return "pin"

        with patched(
            self.common.targets,
            "is_usable_input_target",
            lambda item: item is target,
        ):
            self.assertEqual(
                self.confirm_space.handle_ime_confirm_space_guard(
                    self.win,
                    self.hwnd,
                    self.win.WM_KEYDOWN,
                    self.win.VK_SPACE,
                    0,
                    comp_reader,
                ),
                0,
            )
            self.assertEqual(
                self.confirm_space.handle_ime_confirm_space_guard(
                    self.win,
                    self.hwnd,
                    self.win.WM_KEYUP,
                    self.win.VK_SPACE,
                    0,
                    comp_reader,
                ),
                0,
            )
            self.assertTrue(self.confirm_space.ime_confirm_space_is_active(self.hwnd))

            self.runtime.state.composition_target = None
            result = self.confirm_space.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_CHAR,
                self.win.VK_SPACE,
                0,
                lambda *_args: "",
            )

        self.assertEqual(result, 0)
        self.assertFalse(self.confirm_space.ime_confirm_space_is_active(self.hwnd))

    def test_new_space_after_released_sequence_can_pass_through(self) -> None:
        target = text_editor_target()
        self.runtime.state.composition_target = target

        with patched(
            self.common.targets,
            "is_usable_input_target",
            lambda item: item is target,
        ):
            self.confirm_space.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_KEYDOWN,
                self.win.VK_SPACE,
                0,
                lambda *_args: "pin",
            )
            self.confirm_space.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_KEYUP,
                self.win.VK_SPACE,
                0,
                lambda *_args: "pin",
            )
            self.runtime.state.composition_target = None
            result = self.confirm_space.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_KEYDOWN,
                self.win.VK_SPACE,
                0,
                lambda *_args: "",
            )

        self.assertIsNone(result)

    def test_plain_space_without_composition_passes_through(self) -> None:
        with patched(self.common.targets, "is_usable_input_target", lambda _item: False):
            result = self.confirm_space.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_KEYDOWN,
                self.win.VK_SPACE,
                0,
                lambda *_args: "",
            )
        self.assertIsNone(result)
        self.assertFalse(self.confirm_space.ime_confirm_space_is_active(self.hwnd))

    def test_plain_text_space_does_not_record_leak_snapshot(self) -> None:
        target = text_editor_target()
        self.runtime.state.active_target = target

        with patched(
            self.common.targets,
            "is_usable_input_target",
            lambda item: item is target,
        ):
            result = self.confirm_space.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_KEYDOWN,
                self.win.VK_SPACE,
                0,
                lambda *_args: "",
            )

        self.assertIsNone(result)
        self.assertIsNone(self.runtime.state.text_confirm_space_leak.snapshot)

    def test_recent_text_session_records_possible_leak_snapshot(self) -> None:
        target = text_editor_target()
        text_data = target.text
        self.runtime.state.active_target = target
        self.runtime.state.text_ime_session.begin(
            text=text_data,
            body="",
            line=0,
            column=0,
            select_line=0,
            select_column=0,
            replace_start=0,
            replace_end=0,
        )
        self.runtime.state.text_ime_session.end_current()

        with patched(
            self.common.targets,
            "is_usable_input_target",
            lambda item: item is target,
        ):
            result = self.confirm_space.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_KEYDOWN,
                self.win.VK_SPACE,
                0,
                lambda *_args: "",
            )

        self.assertIsNone(result)
        self.assertIsNotNone(self.runtime.state.text_confirm_space_leak.snapshot)

    def test_hidden_ime_activity_records_possible_leak_snapshot(self) -> None:
        target = text_editor_target()
        self.runtime.state.active_target = target

        with patched(
            self.common.targets,
            "is_usable_input_target",
            lambda item: item is target,
        ):
            self.confirm_space.remember_hidden_text_ime_activity(
                self.win,
                self.hwnd,
                self.win.WM_KEYDOWN,
                self.win.VK_PROCESSKEY,
            )
            result = self.confirm_space.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_KEYDOWN,
                self.win.VK_SPACE,
                0,
                lambda *_args: "",
            )

        self.assertIsNone(result)
        self.assertIsNotNone(self.runtime.state.text_confirm_space_leak.snapshot)
        self.assertIsNone(self.runtime.state.text_hidden_ime_activity.text)

    def test_hidden_font_ime_activity_records_possible_leak_snapshot(self) -> None:
        target = font_target(body="")
        self.runtime.state.active_target = target

        with patched(
            self.common.targets,
            "is_usable_input_target",
            lambda item: item is target,
        ):
            self.confirm_space.remember_hidden_text_ime_activity(
                self.win,
                self.hwnd,
                self.win.WM_KEYDOWN,
                self.win.VK_PROCESSKEY,
            )
            result = self.confirm_space.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_KEYDOWN,
                self.win.VK_SPACE,
                0,
                lambda *_args: "",
            )

        self.assertIsNone(result)
        self.assertIsNotNone(self.runtime.state.font_confirm_space_leak.snapshot)
        self.assertEqual(self.runtime.state.font_hidden_ime_activity.target_key, 0)

    def test_expired_hidden_ime_activity_does_not_record_snapshot(self) -> None:
        target = text_editor_target()
        self.runtime.state.active_target = target
        self.runtime.state.text_hidden_ime_activity.hwnd = self.hwnd
        self.runtime.state.text_hidden_ime_activity.text = target.text
        self.runtime.state.text_hidden_ime_activity.until = 0.0

        with patched(
            self.common.targets,
            "is_usable_input_target",
            lambda item: item is target,
        ):
            result = self.confirm_space.handle_ime_confirm_space_guard(
                self.win,
                self.hwnd,
                self.win.WM_KEYDOWN,
                self.win.VK_SPACE,
                0,
                lambda *_args: "",
            )

        self.assertIsNone(result)
        self.assertIsNone(self.runtime.state.text_confirm_space_leak.snapshot)
        self.assertIsNone(self.runtime.state.text_hidden_ime_activity.text)


if __name__ == "__main__":
    unittest.main()
