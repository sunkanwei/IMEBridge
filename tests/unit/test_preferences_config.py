from types import SimpleNamespace
import unittest

from tests.support.env import import_bridge_module, patched, reset_runtime


class PreferencesConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.config = import_bridge_module("preferences.config")
        self.ime_switch = import_bridge_module("bridge.ime_switch")

    def test_auto_english_on_shortcuts_defaults_to_disabled(self) -> None:
        self.assertFalse(self.config.DEFAULT_AUTO_ENGLISH_ON_SHORTCUTS)
        self.assertFalse(self.config.auto_english_on_shortcuts())

    def test_disabling_auto_english_restores_managed_ime_state(self) -> None:
        calls: list[bool] = []
        preferences = SimpleNamespace(ime_bridge_auto_english_on_shortcuts=False)

        with patched(
            self.ime_switch,
            "restore_all_managed",
            lambda: calls.append(True) or 1,
        ):
            self.config._restore_managed_shortcut_ime_when_disabled(
                preferences,
                None,
            )

        self.assertEqual(calls, [True])

    def test_enabling_auto_english_does_not_restore_managed_ime_state(self) -> None:
        calls: list[bool] = []
        preferences = SimpleNamespace(ime_bridge_auto_english_on_shortcuts=True)

        with patched(
            self.ime_switch,
            "restore_all_managed",
            lambda: calls.append(True) or 1,
        ):
            self.config._restore_managed_shortcut_ime_when_disabled(
                preferences,
                None,
            )

        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
