import unittest

from tests.support.env import import_bridge_module, patched, reset_runtime
from tests.support.fakes import FakeWin, font_target


class FontCommitTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.font_commit = import_bridge_module("bridge.font_commit")
        self.insert_queue = import_bridge_module("targets.queue")

    def test_decode_direct_cjk_and_reject_ascii(self) -> None:
        self.assertEqual(self.font_commit.decode_ime_char_value(ord("中")), "中")
        self.assertEqual(self.font_commit.decode_ime_char_value(ord("A")), "")
        self.assertEqual(self.font_commit.decode_ime_char_value(0x08), "")

    def test_decode_legacy_gbk_pair(self) -> None:
        self.assertEqual(self.font_commit.decode_legacy_two_byte_ime_char(0xD6D0), "中")

    def test_recent_font_result_consumes_echo_once(self) -> None:
        target = font_target(331)
        self.font_commit.mark_recent_font_result(target, "中文")
        self.assertTrue(self.font_commit.is_recent_font_result_char(target, "中"))
        self.assertTrue(self.font_commit.is_recent_font_result_char(target, "文"))
        self.assertFalse(self.font_commit.is_recent_font_result_char(target, "文"))

    def test_font_char_fallback_queues_without_space_suppression_argument(self) -> None:
        target = font_target(332)
        queued: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def queue(*args: object, **kwargs: object) -> None:
            queued.append((args, kwargs))

        win = FakeWin()
        with patched(self.font_commit, "font_input_target_from_state", lambda: target):
            with patched(self.font_commit.insert_queue, "queue", queue):
                result = self.font_commit.handle_font_char_commit(
                    win,
                    77,
                    win.WM_IME_CHAR,
                    ord("中"),
                )

        self.assertEqual(result, 0)
        self.assertEqual(queued[0][0][0], "中")
        self.assertIs(queued[0][0][1], target)
        self.assertEqual(queued[0][1]["source"], self.insert_queue.SOURCE_FONT_CHAR)
        self.assertNotIn("suppress_space", queued[0][1])


if __name__ == "__main__":
    unittest.main()
