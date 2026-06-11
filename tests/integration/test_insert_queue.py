import unittest

from tests.support.env import import_bridge_module, patched, reset_runtime
from tests.support.fakes import font_target, text_editor_target


class InsertQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.queue = import_bridge_module("targets.queue")
        self.runtime = import_bridge_module("core.runtime")

    def font_text_insert_operator(self, target: object) -> object:
        class TextInsert:
            def poll(self) -> bool:
                return True

            def __call__(self, *args: object, **kwargs: object) -> set[str]:
                target.obj.data.body += str(kwargs["text"])
                return {"FINISHED"}

        return TextInsert()

    def test_queue_records_pending_insert_and_arms_timer(self) -> None:
        target = text_editor_target()
        with patched(self.queue.safe_ops, "register_timer", lambda *_args, **_kwargs: True):
            queued = self.queue.queue(
                "A",
                target,
                hwnd=123,
                source=self.queue.SOURCE_DIRECT_ASCII,
            )

        self.assertTrue(queued)
        self.assertTrue(self.runtime.state.insert_timer_registered)
        item = self.runtime.state.pending_inserts[0]
        self.assertEqual(item.text, "A")
        self.assertIs(item.target, target)
        self.assertEqual(item.source, self.queue.SOURCE_DIRECT_ASCII)
        self.assertFalse(hasattr(item, "suppress_space"))

    def test_queue_does_not_leave_pending_insert_when_timer_registration_fails(
        self,
    ) -> None:
        target = text_editor_target()
        with patched(self.queue.safe_ops, "register_timer", lambda *_args, **_kwargs: False):
            queued = self.queue.queue("A", target)

        self.assertFalse(queued)
        self.assertFalse(self.runtime.state.insert_timer_registered)
        self.assertEqual(len(self.runtime.state.pending_inserts), 0)

    def test_empty_text_is_not_queued(self) -> None:
        target = text_editor_target()
        self.assertFalse(self.queue.queue("", target))
        self.assertEqual(len(self.runtime.state.pending_inserts), 0)

    def test_font_char_fallback_allows_repeated_identical_commits(self) -> None:
        target = font_target(body="")

        with patched(self.queue.safe_ops, "register_timer", lambda *_args, **_kwargs: True):
            self.assertTrue(
                self.queue.queue(
                    "中",
                    target,
                    source=self.queue.SOURCE_FONT_CHAR,
                )
            )
            self.assertTrue(
                self.queue.queue(
                    "中",
                    target,
                    source=self.queue.SOURCE_FONT_CHAR,
                )
            )

        with patched(
            self.queue.font_target.bpy.ops.font,
            "text_insert",
            self.font_text_insert_operator(target),
        ):
            self.queue.flush()

        self.assertEqual(target.obj.data.body, "中中")

    def test_font_result_echo_is_still_deduplicated(self) -> None:
        target = font_target(body="")

        with patched(self.queue.safe_ops, "register_timer", lambda *_args, **_kwargs: True):
            self.assertTrue(
                self.queue.queue(
                    "中",
                    target,
                    source=self.queue.SOURCE_IME_RESULT,
                )
            )
            self.assertTrue(
                self.queue.queue(
                    "中",
                    target,
                    source=self.queue.SOURCE_FONT_CHAR,
                )
            )

        with patched(
            self.queue.font_target.bpy.ops.font,
            "text_insert",
            self.font_text_insert_operator(target),
        ):
            self.queue.flush()

        self.assertEqual(target.obj.data.body, "中")


if __name__ == "__main__":
    unittest.main()
