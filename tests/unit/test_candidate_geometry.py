import unittest
from types import SimpleNamespace

from tests.support.env import import_bridge_module, patched, reset_runtime


class CandidateGeometryTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.caret = import_bridge_module("targets.caret")
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


if __name__ == "__main__":
    unittest.main()
