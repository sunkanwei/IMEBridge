from types import SimpleNamespace
import unittest

from tests.support.env import import_bridge_module, patched, reset_runtime
from tests.support.fakes import font_target, text_editor_target


class MacOSEventBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.bridge = import_bridge_module("bridge.macos_event_bridge")
        self.input_scope = import_bridge_module("bridge.input_scope")

    def shortcut_scope(self) -> object:
        return self.input_scope.InputScope(
            self.input_scope.SCOPE_SHORTCUT_SURFACE,
            hit=SimpleNamespace(area=SimpleNamespace(type="NODE_EDITOR")),
        )

    def install_shortcut_hit(self):
        api = SimpleNamespace(
            mouse_location=lambda: SimpleNamespace(x=10, y=20),
        )
        hit = SimpleNamespace(area=SimpleNamespace(type="NODE_EDITOR"))
        return (
            patched(self.bridge.platform_api, "ensure", lambda: api),
            patched(
                self.bridge.input_scope,
                "area_hit_at_window_point",
                lambda *_args: hit,
            ),
            patched(
                self.bridge.input_scope,
                "classify_hit",
                lambda *_args: self.shortcut_scope(),
            ),
        )

    def test_ime_allowed_respects_auto_english_preference(self) -> None:
        ensure_patch, hit_patch, classify_patch = self.install_shortcut_hit()
        with ensure_patch, hit_patch, classify_patch:
            with patched(
                self.bridge.config,
                "auto_english_on_shortcuts",
                lambda: True,
            ):
                self.assertFalse(self.bridge.is_ime_allowed())

            with patched(
                self.bridge.config,
                "auto_english_on_shortcuts",
                lambda: False,
            ):
                self.assertTrue(self.bridge.is_ime_allowed())

    def test_shortcut_poll_does_not_end_ime_when_preference_is_disabled(self) -> None:
        ensure_patch, hit_patch, classify_patch = self.install_shortcut_hit()
        ended: list[bool] = []
        cleared: list[bool] = []

        with ensure_patch, hit_patch, classify_patch:
            with patched(self.bridge, "_RUNNING", True):
                with patched(self.bridge, "active_hwnd", lambda: 44):
                    with patched(
                        self.bridge.targets,
                        "font_object_for_ime",
                        lambda *_args, **_kwargs: None,
                    ):
                        with patched(
                            self.bridge,
                            "clear_bridge_target_state",
                            lambda: cleared.append(True),
                        ):
                            with patched(
                                self.bridge,
                                "end_ime",
                                lambda: ended.append(True) or True,
                            ):
                                with patched(
                                    self.bridge.config,
                                    "auto_english_on_shortcuts",
                                    lambda: False,
                                ):
                                    self.assertEqual(
                                        self.bridge._target_poll_timer(),
                                        self.bridge.TARGET_POLL_INTERVAL,
                                    )

        self.assertEqual(cleared, [True])
        self.assertEqual(ended, [])

    def test_shortcut_poll_ends_ime_when_preference_is_enabled(self) -> None:
        ensure_patch, hit_patch, classify_patch = self.install_shortcut_hit()
        ended: list[bool] = []

        with ensure_patch, hit_patch, classify_patch:
            with patched(self.bridge, "_RUNNING", True):
                with patched(self.bridge, "active_hwnd", lambda: 44):
                    with patched(
                        self.bridge.targets,
                        "font_object_for_ime",
                        lambda *_args, **_kwargs: None,
                    ):
                        with patched(
                            self.bridge,
                            "clear_bridge_target_state",
                            lambda: None,
                        ):
                            with patched(
                                self.bridge,
                                "end_ime",
                                lambda: ended.append(True) or True,
                            ):
                                with patched(
                                    self.bridge.config,
                                    "auto_english_on_shortcuts",
                                    lambda: True,
                                ):
                                    self.assertEqual(
                                        self.bridge._target_poll_timer(),
                                        self.bridge.TARGET_POLL_INTERVAL,
                                    )

        self.assertEqual(ended, [True])

    def test_shortcut_commit_does_not_use_stale_bridge_target(self) -> None:
        ensure_patch, hit_patch, classify_patch = self.install_shortcut_hit()
        target = text_editor_target()
        queued: list[bool] = []
        self.bridge.runtime.state.active_target = target

        with ensure_patch, hit_patch, classify_patch:
            with patched(self.bridge, "_RUNNING", True):
                with patched(self.bridge, "active_hwnd", lambda: 44):
                    with patched(
                        self.bridge.targets,
                        "font_object_for_ime",
                        lambda *_args, **_kwargs: None,
                    ):
                        with patched(
                            self.bridge.targets,
                            "is_usable_input_target",
                            lambda item: item is target,
                        ):
                            with patched(
                                self.bridge.insert_queue,
                                "queue",
                                lambda *_args, **_kwargs: queued.append(True) or True,
                            ):
                                self.assertFalse(
                                    self.bridge.handle_committed_text("中")
                                )

        self.assertEqual(queued, [])

    def test_shortcut_commit_allows_view3d_font_edit_target(self) -> None:
        api = SimpleNamespace(
            mouse_location=lambda: SimpleNamespace(x=10, y=20),
        )
        hit = SimpleNamespace(area=SimpleNamespace(type="VIEW_3D"))
        target = font_target()
        queued: list[tuple[str, object]] = []
        self.bridge.runtime.state.active_target = target

        with patched(self.bridge.platform_api, "ensure", lambda: api):
            with patched(
                self.bridge.input_scope,
                "area_hit_at_window_point",
                lambda *_args: hit,
            ):
                with patched(
                    self.bridge.input_scope,
                    "classify_hit",
                    lambda *_args: self.input_scope.InputScope(
                        self.input_scope.SCOPE_SHORTCUT_SURFACE,
                        hit=hit,
                    ),
                ):
                    with patched(self.bridge, "_RUNNING", True):
                        with patched(self.bridge, "active_hwnd", lambda: 44):
                            with patched(
                                self.bridge.targets,
                                "font_object_for_ime",
                                lambda *_args, **_kwargs: target.obj,
                            ):
                                with patched(
                                    self.bridge.targets,
                                    "is_usable_input_target",
                                    lambda item: item is target,
                                ):
                                    with patched(
                                        self.bridge.insert_queue,
                                        "queue",
                                        lambda text, item, *_args, **_kwargs: queued.append(
                                            (text, item)
                                        )
                                        or True,
                                    ):
                                        self.assertTrue(
                                            self.bridge.handle_committed_text("中")
                                        )

        self.assertEqual(queued, [("中", target)])


if __name__ == "__main__":
    unittest.main()
