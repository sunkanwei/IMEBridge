from __future__ import annotations

import importlib
import sys
import unittest

from tests.support.env import PACKAGE_PARENT
from tests.support.env import install_fake_bpy
from tests.support.env import patched
from tests.support.env import reset_runtime


class StatefulClassUtils:
    def __init__(self) -> None:
        self.registered: set[type] = set()
        self.calls: list[tuple[str, str]] = []

    def register_class(self, cls: type) -> None:
        self.calls.append(("register", cls.__name__))
        if cls in self.registered:
            raise RuntimeError(f"{cls.__name__} already registered")
        self.registered.add(cls)

    def unregister_class(self, cls: type) -> None:
        self.calls.append(("unregister", cls.__name__))
        if cls not in self.registered:
            raise RuntimeError(f"{cls.__name__} is not registered")
        self.registered.remove(cls)


def import_addon() -> object:
    install_fake_bpy()
    package_parent = str(PACKAGE_PARENT)
    if package_parent not in sys.path:
        sys.path.insert(0, package_parent)
    return importlib.import_module("IMEBridge")


class AddonLifecycleTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_runtime()

    def test_register_uses_standard_classes_list(self) -> None:
        bpy = install_fake_bpy()
        addon = import_addon()
        utils = StatefulClassUtils()
        events: list[str] = []
        preferences_cls = addon.config.IMEBridgePreferences

        self.assertEqual(addon.classes, (preferences_cls,))
        self.assertFalse(hasattr(addon, "_REGISTERED_CLASSES"))

        with patched(bpy, "utils", utils):
            with patched(addon.i18n, "register", lambda: events.append("i18n")):
                with patched(
                    addon.ime_context,
                    "register_text_draw_handler",
                    lambda: events.append("draw"),
                ):
                    with patched(
                        addon.window_hook,
                        "schedule_auto_enable",
                        lambda: events.append("auto"),
                    ):
                        addon.register()

        self.assertIn(preferences_cls, utils.registered)
        self.assertEqual(utils.calls, [("register", preferences_cls.__name__)])
        self.assertEqual(events, ["i18n", "draw", "auto"])

    def test_unregister_stops_runtime_before_classes(self) -> None:
        bpy = install_fake_bpy()
        addon = import_addon()
        preferences_cls = addon.config.IMEBridgePreferences
        events: list[str] = []

        class EventClassUtils(StatefulClassUtils):
            def unregister_class(self, cls: type) -> None:
                super().unregister_class(cls)
                events.append(f"unregister:{cls.__name__}")

        utils = EventClassUtils()
        utils.registered.add(preferences_cls)

        with patched(bpy, "utils", utils):
            with patched(
                addon.window_hook,
                "cancel_auto_enable",
                lambda: events.append("cancel"),
            ):
                with patched(
                    addon.ime_context,
                    "unregister_text_draw_handler",
                    lambda: events.append("draw"),
                ):
                    with patched(
                        addon.window_hook,
                        "stop_hooks",
                        lambda: events.append("hooks") or 0,
                    ):
                        with patched(
                            addon.i18n,
                            "unregister",
                            lambda: events.append("i18n"),
                        ):
                            addon.unregister()

        self.assertNotIn(preferences_cls, utils.registered)
        self.assertEqual(
            events,
            [
                "cancel",
                "draw",
                "hooks",
                f"unregister:{preferences_cls.__name__}",
                "i18n",
            ],
        )

    def test_register_propagates_class_registration_errors(self) -> None:
        bpy = install_fake_bpy()
        addon = import_addon()
        utils = StatefulClassUtils()
        preferences_cls = addon.config.IMEBridgePreferences
        utils.registered.add(preferences_cls)

        with patched(bpy, "utils", utils):
            try:
                with self.assertRaises(RuntimeError):
                    addon.register()
            finally:
                utils.registered.discard(preferences_cls)


if __name__ == "__main__":
    unittest.main()
