import unittest

from tests.support.env import import_bridge_module, reset_runtime


class FacadeTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()

    def test_guard_facade_keeps_legacy_exports(self) -> None:
        guards = import_bridge_module("bridge.ime_guards")
        expected = {
            "SPACE_CONFIRM_STALE_SECONDS",
            "DIRECT_ASCII_STALE_SECONDS",
            "handle_ime_confirm_space_guard",
            "remember_hidden_text_ime_activity",
            "handle_direct_ascii_guard",
            "handle_preedit_text_guard",
            "handle_raw_input_guard",
            "handle_ime_edit_key_guard",
            "handle_message_guards",
        }
        self.assertLessEqual(expected, set(guards.__all__))
        for name in expected:
            self.assertTrue(hasattr(guards, name), name)

    def test_text_facade_keeps_legacy_exports(self) -> None:
        text = import_bridge_module("targets.text")
        expected = {
            "TEXT_RESTORE_TIMER_INTERVAL",
            "TEXT_TAB_INDENT_TIMER_INTERVAL",
            "text_position_to_offset",
            "capture_composition_start",
            "schedule_restore_guard",
            "remember_possible_confirm_space_leak",
            "clear_confirm_space_leak",
            "consume_confirm_space_leak_session",
            "schedule_tab_indent",
            "insert_text_session_result",
            "insert",
        }
        self.assertLessEqual(expected, set(text.__all__))
        for name in expected:
            self.assertTrue(hasattr(text, name), name)

    def test_message_router_facade_keeps_diagnostic_exports(self) -> None:
        router = import_bridge_module("bridge.message_router")
        expected = {
            "INPUT_SCOPE_TIMER_INTERVAL",
            "TEXT_AREA_ACTIVATION_INTERVAL",
            "apply_enabled_scope",
            "apply_shortcut_scope",
            "scope_target_from_context",
            "handle_window_message",
        }
        self.assertLessEqual(expected, set(router.__all__))
        for name in expected:
            self.assertTrue(hasattr(router, name), name)


if __name__ == "__main__":
    unittest.main()
