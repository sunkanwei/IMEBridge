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

    def test_register_clears_stale_preferences_class_before_retry(self) -> None:
        bpy = install_fake_bpy()
        addon = import_addon()
        utils = StatefulClassUtils()
        preferences_cls = addon._REGISTERED_CLASSES[0]
        utils.registered.add(preferences_cls)

        with patched(bpy, "utils", utils):
            try:
                addon.register()

                self.assertIn(preferences_cls, utils.registered)
                self.assertEqual(
                    utils.calls[:2],
                    [
                        ("unregister", preferences_cls.__name__),
                        ("register", preferences_cls.__name__),
                    ],
                )
            finally:
                addon.unregister()

        self.assertNotIn(preferences_cls, utils.registered)


if __name__ == "__main__":
    unittest.main()
