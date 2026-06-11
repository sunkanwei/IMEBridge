import unittest

from tests.support.env import import_bridge_module, patched, reset_runtime
from tests.support.fakes import text_editor_target


class InsertQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.queue = import_bridge_module("targets.queue")
        self.runtime = import_bridge_module("core.runtime")

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


if __name__ == "__main__":
    unittest.main()
