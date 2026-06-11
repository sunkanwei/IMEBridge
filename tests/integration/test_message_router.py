import unittest

from tests.support.env import import_bridge_module, patched, reset_runtime
from tests.support.fakes import FakeWin, font_target, text_editor_target


class MessageRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.router = import_bridge_module("bridge.message_router")
        self.runtime = import_bridge_module("core.runtime")
        self.queue = import_bridge_module("targets.queue")
        self.win = FakeWin()

    def test_clear_bridge_target_state_clears_recent_guard_state(self) -> None:
        self.runtime.state.active_target = object()
        self.runtime.state.composition_target = object()
        self.runtime.state.ime_confirm_space.hwnd = 1
        self.runtime.state.ime_direct_ascii.hwnd = 2
        self.runtime.state.ime_direct_ascii.pending_chars = 1
        self.runtime.state.text_restore_guard = object()
        self.runtime.state.text_restore_timer_registered = True
        self.runtime.state.tab_indent.count = 1

        self.router.clear_bridge_target_state()

        self.assertIsNone(self.runtime.state.active_target)
        self.assertIsNone(self.runtime.state.composition_target)
        self.assertEqual(self.runtime.state.ime_confirm_space.hwnd, 0)
        self.assertEqual(self.runtime.state.ime_direct_ascii.hwnd, 0)
        self.assertIsNone(self.runtime.state.text_restore_guard)
        self.assertFalse(self.runtime.state.text_restore_timer_registered)
        self.assertEqual(self.runtime.state.tab_indent.count, 0)

    def test_queue_ime_result_uses_current_queue_signature(self) -> None:
        target = font_target(778)
        queued: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def queue(*args: object, **kwargs: object) -> None:
            queued.append((args, kwargs))

        self.runtime.state.insert_on_commit = True
        is_target = lambda item: item is target
        with patched(self.router, "bridge_ime_allowed", lambda: True):
            with patched(self.router, "resolve_input_target_from_state", lambda: target):
                with patched(self.router.targets, "is_usable_input_target", is_target):
                    with patched(self.router.insert_queue, "queue", queue):
                        self.router.queue_ime_result(55, "中")

        self.assertEqual(queued[0][0][0], "中")
        self.assertIs(queued[0][0][1], target)
        self.assertEqual(queued[0][1]["source"], self.queue.SOURCE_IME_RESULT)
        self.assertNotIn("suppress_space", queued[0][1])

    def test_unicode_text_tab_schedules_indent_only_for_plain_raw_tab(self) -> None:
        target = text_editor_target()
        with patched(
            self.router.platform_api,
            "read_raw_keyboard",
            lambda *_args: {"vkey": self.win.VK_TAB, "key_down": 1},
        ):
            with patched(self.router, "bridge_ime_allowed", lambda: True):
                with patched(self.router.ime_guards, "ime_is_composing", lambda *_args: False):
                    with patched(
                        self.router.targets,
                        "resolve_input_target",
                        lambda *_args: target,
                    ):
                        with patched(
                            self.router.text_target,
                            "cursor_after_non_ascii_identifier",
                            lambda item: item is target,
                        ):
                            with patched(
                                self.router.text_target,
                                "schedule_tab_indent",
                                lambda item: item is target,
                            ):
                                result = self.router.handle_unicode_text_tab(
                                    self.win,
                                    44,
                                    self.win.WM_INPUT,
                                    9,
                                )
        self.assertEqual(result, 0)

    def test_unicode_text_tab_passes_through_when_shift_is_down(self) -> None:
        target = text_editor_target()
        self.win.user32.key_state[self.win.VK_SHIFT] = 0x8000
        with patched(
            self.router.platform_api,
            "read_raw_keyboard",
            lambda *_args: {"vkey": self.win.VK_TAB, "key_down": 1},
        ):
            with patched(self.router, "bridge_ime_allowed", lambda: True):
                with patched(self.router.ime_guards, "ime_is_composing", lambda *_args: False):
                    with patched(
                        self.router.targets,
                        "resolve_input_target",
                        lambda *_args: target,
                    ):
                        result = self.router.handle_unicode_text_tab(
                            self.win,
                            44,
                            self.win.WM_INPUT,
                            9,
                        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
