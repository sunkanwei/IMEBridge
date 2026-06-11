import unittest

from tests.support.env import import_bridge_module, patched, reset_runtime
from tests.support.fakes import FakeText, FakeWin, font_target, text_editor_target


class MessageRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.router = import_bridge_module("bridge.message_router")
        self.font_commit = import_bridge_module("bridge.font_commit")
        self.runtime = import_bridge_module("core.runtime")
        self.queue = import_bridge_module("targets.queue")
        self.font_restore = import_bridge_module("targets.font_restore")
        self.text = import_bridge_module("targets.text")
        self.win = FakeWin()

    def test_clear_bridge_target_state_clears_recent_guard_state(self) -> None:
        self.runtime.state.active_target = object()
        self.runtime.state.composition_target = object()
        self.runtime.state.ime_confirm_space.hwnd = 1
        self.runtime.state.ime_direct_ascii.hwnd = 2
        self.runtime.state.ime_direct_ascii.pending_chars = 1
        self.runtime.state.text_restore_guard = object()
        self.runtime.state.text_restore_timer_registered = True
        self.runtime.state.text_confirm_space_leak.snapshot = object()
        self.runtime.state.text_hidden_ime_activity.text = object()
        self.runtime.state.font_confirm_space_leak.snapshot = object()
        self.runtime.state.font_hidden_ime_activity.target_key = 9
        text_data = FakeText("", line=0, column=0)
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
        self.runtime.state.tab_indent.count = 1
        resets: list[object] = []

        with patched(
            self.router.ime_context,
            "reset_ime_candidate_position",
            lambda hwnd=None: resets.append(hwnd) or True,
        ):
            self.router.clear_bridge_target_state(44)

        self.assertIsNone(self.runtime.state.active_target)
        self.assertIsNone(self.runtime.state.composition_target)
        self.assertEqual(self.runtime.state.ime_confirm_space.hwnd, 0)
        self.assertEqual(self.runtime.state.ime_direct_ascii.hwnd, 0)
        self.assertIsNone(self.runtime.state.text_restore_guard)
        self.assertFalse(self.runtime.state.text_restore_timer_registered)
        self.assertIsNone(self.runtime.state.text_ime_session.current)
        self.assertIsNone(self.runtime.state.text_ime_session.recent)
        self.assertIsNone(self.runtime.state.text_confirm_space_leak.snapshot)
        self.assertIsNone(self.runtime.state.text_hidden_ime_activity.text)
        self.assertIsNone(self.runtime.state.font_confirm_space_leak.snapshot)
        self.assertEqual(self.runtime.state.font_hidden_ime_activity.target_key, 0)
        self.assertEqual(self.runtime.state.tab_indent.count, 0)
        self.assertEqual(resets, [44])

    def test_clear_bridge_target_state_does_not_reset_without_bridge_target(
        self,
    ) -> None:
        resets: list[object] = []

        with patched(
            self.router.ime_context,
            "reset_ime_candidate_position",
            lambda hwnd=None: resets.append(hwnd) or True,
        ):
            self.router.clear_bridge_target_state(44)

        self.assertEqual(resets, [])

    def test_queue_ime_result_uses_current_queue_signature(self) -> None:
        target = font_target(778)
        queued: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def queue(*args: object, **kwargs: object) -> bool:
            queued.append((args, kwargs))
            return True

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

    def test_ime_start_does_not_bind_neutral_scope_to_old_text_target(self) -> None:
        old_target = text_editor_target()
        self.runtime.state.active_target = old_target
        self.runtime.state.input_scope.current_kind = self.router.input_scope.SCOPE_NEUTRAL

        with patched(
            self.router.ime_context,
            "reset_ime_candidate_position",
            lambda *_args: True,
        ):
            with patched(
                self.router.targets,
                "make_input_target_from_context",
                lambda _context: None,
            ):
                with patched(
                    self.router.targets,
                    "is_usable_input_target",
                    lambda item: item is old_target,
                ):
                    self.router.handle_ime_start_composition(44)

        self.assertIsNone(self.runtime.state.active_target)
        self.assertIsNone(self.runtime.state.composition_target)
        self.assertIsNone(self.runtime.state.text_ime_session.current)

    def test_bridge_ime_allowed_uses_current_context_in_neutral_scope(self) -> None:
        target = text_editor_target()
        self.runtime.state.active_target = object()
        self.runtime.state.input_scope.current_kind = self.router.input_scope.SCOPE_NEUTRAL

        with patched(
            self.router.targets,
            "make_input_target_from_context",
            lambda _context: target,
        ):
            with patched(
                self.router.targets,
                "is_usable_input_target",
                lambda item: item is target,
            ):
                self.assertTrue(self.router.bridge_ime_allowed())

    def test_queue_ime_result_uses_recent_session_after_end_and_leaked_space(self) -> None:
        text_data = FakeText("", line=0, column=0)
        target = text_editor_target(text_data)
        self.runtime.state.insert_on_commit = True
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
        self.router.handle_ime_end_composition(44)
        text_data.write(" ")
        text_data.select_set(0, 1, 0, 1)

        with patched(self.router, "bridge_ime_allowed", lambda: True):
            with patched(self.router, "resolve_input_target_from_state", lambda: target):
                with patched(
                    self.router.targets,
                    "is_usable_input_target",
                    lambda item: item is target,
                ):
                    self.router.queue_ime_result(44, "中")
        self.queue.flush()

        self.assertEqual(text_data.as_string(), "中")

    def test_queue_ime_result_repairs_suspected_confirm_space_leak(self) -> None:
        text_data = FakeText("", line=0, column=0)
        target = text_editor_target(text_data)
        self.runtime.state.insert_on_commit = True
        self.text.remember_possible_confirm_space_leak(44, target)
        text_data.write(" ")
        text_data.select_set(0, 1, 0, 1)

        with patched(self.router, "bridge_ime_allowed", lambda: True):
            with patched(self.router, "resolve_input_target_from_state", lambda: target):
                with patched(
                    self.router.targets,
                    "is_usable_input_target",
                    lambda item: item is target,
                ):
                    self.router.queue_ime_result(44, "中")
        self.queue.flush()

        self.assertEqual(text_data.as_string(), "中")

    def test_queue_ime_result_prefers_leak_session_over_polluted_current_session(
        self,
    ) -> None:
        text_data = FakeText("", line=0, column=0)
        target = text_editor_target(text_data)
        self.runtime.state.insert_on_commit = True
        self.text.remember_possible_confirm_space_leak(44, target)
        text_data.write(" ")
        text_data.select_set(0, 1, 0, 1)
        self.runtime.state.text_ime_session.begin(
            text=text_data,
            body=" ",
            line=0,
            column=1,
            select_line=0,
            select_column=1,
            replace_start=1,
            replace_end=1,
        )

        with patched(self.router, "bridge_ime_allowed", lambda: True):
            with patched(self.router, "resolve_input_target_from_state", lambda: target):
                with patched(
                    self.router.targets,
                    "is_usable_input_target",
                    lambda item: item is target,
                ):
                    self.router.queue_ime_result(44, "中")
        self.queue.flush()

        self.assertEqual(text_data.as_string(), "中")
        self.assertTrue(self.runtime.state.text_ime_session.current.committed)

    def test_queue_ime_result_does_not_reuse_committed_current_session(self) -> None:
        text_data = FakeText("", line=0, column=0)
        target = text_editor_target(text_data)
        self.runtime.state.insert_on_commit = True
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

        def insert(
            value: str,
            item: object,
            text_session: object = None,
        ) -> bool:
            if text_session is not None:
                body, line, column = self.text.text_session_commit_result(
                    text_session,
                    value,
                )
                text_data.write(body)
                text_data.select_set(line, column, line, column)
                return True
            return self.text.insert_text_body_at_cursor(text_data, value)

        with patched(self.router, "bridge_ime_allowed", lambda: True):
            with patched(self.router, "resolve_input_target_from_state", lambda: target):
                with patched(
                    self.router.targets,
                    "is_usable_input_target",
                    lambda item: item is target,
                ):
                    self.router.queue_ime_result(44, "你")
                    self.router.queue_ime_result(44, "好")
        with patched(self.queue.text_target, "insert", insert):
            self.queue.flush()

        self.assertEqual(text_data.as_string(), "你好")

    def test_queue_ime_result_repairs_font_confirm_space_leak(self) -> None:
        target = font_target(780, body="")
        self.runtime.state.insert_on_commit = True
        self.font_restore.remember_hidden_ime_activity(44, target)
        self.font_restore.remember_possible_confirm_space_leak(44, target)
        target.obj.data.body = " "

        class DeletePrevious:
            def poll(self) -> bool:
                return True

            def __call__(self, *args: object, **kwargs: object) -> set[str]:
                target.obj.data.body = target.obj.data.body[:-1]
                return {"FINISHED"}

        class TextInsert:
            def poll(self) -> bool:
                return True

            def __call__(self, *args: object, **kwargs: object) -> set[str]:
                target.obj.data.body += str(kwargs["text"])
                return {"FINISHED"}

        with patched(self.router, "bridge_ime_allowed", lambda: True):
            with patched(self.router, "resolve_input_target_from_state", lambda: target):
                with patched(
                    self.router.targets,
                    "is_usable_input_target",
                    lambda item: item is target,
                ):
                    self.router.queue_ime_result(44, "中")
        with patched(self.queue.font_target.bpy.ops.font, "delete", DeletePrevious()):
            with patched(
                self.queue.font_target.bpy.ops.font,
                "text_insert",
                TextInsert(),
            ):
                self.queue.flush()

        self.assertEqual(target.obj.data.body, "中")

    def test_font_char_fallback_repairs_confirm_space_leak(self) -> None:
        target = font_target(781, body="")
        self.font_restore.remember_hidden_ime_activity(44, target)
        self.font_restore.remember_possible_confirm_space_leak(44, target)
        target.obj.data.body = " "

        class DeletePrevious:
            def poll(self) -> bool:
                return True

            def __call__(self, *args: object, **kwargs: object) -> set[str]:
                target.obj.data.body = target.obj.data.body[:-1]
                return {"FINISHED"}

        class TextInsert:
            def poll(self) -> bool:
                return True

            def __call__(self, *args: object, **kwargs: object) -> set[str]:
                target.obj.data.body += str(kwargs["text"])
                return {"FINISHED"}

        with patched(self.font_commit, "font_input_target_from_state", lambda: target):
            result = self.font_commit.handle_font_char_commit(
                self.win,
                44,
                self.win.WM_IME_CHAR,
                ord("中"),
            )
        with patched(self.queue.font_target.bpy.ops.font, "delete", DeletePrevious()):
            with patched(
                self.queue.font_target.bpy.ops.font,
                "text_insert",
                TextInsert(),
            ):
                self.queue.flush()

        self.assertEqual(result, 0)
        self.assertEqual(target.obj.data.body, "中")

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
