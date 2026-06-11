import unittest
from types import SimpleNamespace

from tests.support.env import import_bridge_module, patched, reset_runtime
from tests.support.fakes import FakeWin


class CandidateGeometryTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.caret = import_bridge_module("targets.caret")
        self.ime_context = import_bridge_module("bridge.ime_context")
        self.models = import_bridge_module("core.models")

    def test_text_editor_position_applies_requested_and_manual_offsets(self) -> None:
        info = self.models.CandidateInfo(
            space=SimpleNamespace(
                font_size=20,
                region_location_from_cursor=lambda _line, column: (column * 10, 0),
            ),
            screen_x=100,
            screen_y=200,
            line_height=18,
            rect=object(),
            line=0,
            column=2,
        )

        with patched(self.caret.config, "add_requested_char_offset", lambda: True):
            with patched(self.caret.config, "x_offset", lambda: -30):
                with patched(self.caret.config, "y_offset", lambda: -40):
                    position = self.caret.ime_candidate_position(info, requested_char=3)

        self.assertEqual((position.screen_x, position.screen_y), (100, 160))

    def test_text_line_height_prefers_visible_lines(self) -> None:
        space = SimpleNamespace(visible_lines=10, font_size=32)
        region = SimpleNamespace(height=300)
        self.assertEqual(self.caret.text_line_height(space, region), 30)

    def test_reset_ime_candidate_position_restores_default_forms(self) -> None:
        if not hasattr(self.ime_context.platform_api, "COMPOSITIONFORM"):
            self.skipTest("Win32 form structs are unavailable on this platform")

        win = FakeWin()
        hwnd = 44

        with patched(self.ime_context.platform_api, "backend_name", lambda: "windows"):
            with patched(self.ime_context.platform_api, "ensure", lambda: win):
                with patched(
                    self.ime_context,
                    "ghost_window_for_ime",
                    lambda _win, _hwnd=None: hwnd,
                ):
                    self.assertTrue(self.ime_context.reset_ime_candidate_position())

        self.assertEqual(
            [form.dwStyle for form in win.imm32.composition_windows],
            [win.CFS_DEFAULT],
        )
        self.assertEqual(
            [(form.dwIndex, form.dwStyle) for form in win.imm32.candidate_windows],
            [
                (0, win.CFS_DEFAULT),
                (1, win.CFS_DEFAULT),
                (2, win.CFS_DEFAULT),
                (3, win.CFS_DEFAULT),
            ],
        )


if __name__ == "__main__":
    unittest.main()
