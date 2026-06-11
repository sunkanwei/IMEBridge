import unittest

from tests.support.env import import_bridge_module, patched, reset_runtime
from tests.support.fakes import FakeText, text_editor_target


class TextTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.text = import_bridge_module("targets.text")
        self.text_indent = import_bridge_module("targets.text_indent")
        self.runtime = import_bridge_module("core.runtime")

    def test_offsets_round_trip_multiline_unicode(self) -> None:
        body = "alpha\n中文beta\nomega"
        offset = self.text.text_position_to_offset(body, 1, 2)
        self.assertEqual(offset, len("alpha\n中文"))
        self.assertEqual(self.text.text_offset_to_position(body, offset), (1, 2))

    def test_selection_offsets_are_sorted(self) -> None:
        body = "abc\ndef"
        self.assertEqual(self.text.text_selection_offsets(body, 1, 2, 0, 1), (1, 6))

    def test_session_commit_replaces_saved_selection(self) -> None:
        models = import_bridge_module("core.models")
        session = models.TextImeSession(
            text=object(),
            body="hello world",
            line=0,
            column=6,
            select_line=0,
            select_column=11,
            replace_start=6,
            replace_end=11,
        )
        body, line, column = self.text.text_session_commit_result(session, "中文")
        self.assertEqual(body, "hello 中文")
        self.assertEqual((line, column), (0, 8))

    def test_cursor_after_non_ascii_identifier_requires_no_selection(self) -> None:
        target = text_editor_target(FakeText("变量", line=0, column=2))
        self.assertTrue(self.text.cursor_after_non_ascii_identifier(target))

        selected = text_editor_target(
            FakeText("变量", line=0, column=2, select_line=0, select_column=1)
        )
        self.assertFalse(self.text.cursor_after_non_ascii_identifier(selected))

        ascii_target = text_editor_target(FakeText("name", line=0, column=4))
        self.assertFalse(self.text.cursor_after_non_ascii_identifier(ascii_target))

    def test_tab_indent_state_rolls_back_when_timer_registration_fails(self) -> None:
        target = text_editor_target(FakeText("变量", line=0, column=2))
        with patched(
            self.text_indent.safe_ops,
            "register_timer",
            lambda *_a, **_kw: False,
        ):
            self.assertFalse(self.text.schedule_tab_indent(target))
        self.assertEqual(self.runtime.state.tab_indent.count, 0)
        self.assertIsNone(self.runtime.state.tab_indent.target)

    def test_tab_indent_state_batches_when_timer_is_registered(self) -> None:
        target = text_editor_target(FakeText("变量", line=0, column=2))
        with patched(
            self.text_indent.safe_ops,
            "register_timer",
            lambda *_a, **_kw: True,
        ):
            self.assertTrue(self.text.schedule_tab_indent(target))
            self.assertTrue(self.text.schedule_tab_indent(target))
        self.assertEqual(self.runtime.state.tab_indent.count, 2)
        self.assertIs(self.runtime.state.tab_indent.target, target)
        self.assertTrue(self.runtime.state.tab_indent.timer_registered)

    def test_confirm_space_leak_guard_requires_non_ascii_result(self) -> None:
        target = text_editor_target(FakeText("", line=0, column=0))
        self.text.remember_possible_confirm_space_leak(44, target)
        target.text.write(" ")
        target.text.select_set(0, 1, 0, 1)

        session, text = self.text.consume_confirm_space_leak_session(
            44,
            target,
            "a",
        )

        self.assertIsNone(session)
        self.assertEqual(text, "a")
        self.assertIsNone(self.runtime.state.text_confirm_space_leak.snapshot)

    def test_confirm_space_leak_guard_builds_replacement_session(self) -> None:
        target = text_editor_target(FakeText("", line=0, column=0))
        self.text.remember_possible_confirm_space_leak(44, target)
        target.text.write(" ")
        target.text.select_set(0, 1, 0, 1)

        session, text = self.text.consume_confirm_space_leak_session(
            44,
            target,
            " 中文",
        )

        self.assertIsNotNone(session)
        self.assertEqual(text, "中文")
        self.assertEqual(self.text.text_session_commit_result(session, text)[0], "中文")

    def test_confirm_space_leak_guard_keeps_first_snapshot(self) -> None:
        target = text_editor_target(FakeText("", line=0, column=0))
        self.text.remember_possible_confirm_space_leak(44, target)
        target.text.write(" ")
        target.text.select_set(0, 1, 0, 1)
        self.text.remember_possible_confirm_space_leak(44, target)

        session, text = self.text.consume_confirm_space_leak_session(
            44,
            target,
            "中文",
        )

        self.assertIsNotNone(session)
        self.assertEqual(self.text.text_session_commit_result(session, text)[0], "中文")


if __name__ == "__main__":
    unittest.main()
