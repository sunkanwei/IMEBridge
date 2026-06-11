import unittest

from tests.support.env import import_bridge_module, patched, reset_runtime
from tests.support.fakes import FakeWin


class ImeSwitchTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.ime_switch = import_bridge_module("bridge.ime_switch")
        self.runtime = import_bridge_module("core.runtime")
        self.win = FakeWin()

    def test_close_records_state_and_restore_reopens_only_managed_ime(self) -> None:
        self.win.imm32.open_status = True
        self.win.imm32.conversion = 7
        self.win.imm32.sentence = 9

        with patched(self.ime_switch.platform_api, "ensure", lambda: self.win):
            self.assertTrue(self.ime_switch.close_for_shortcut_surface(88))
            self.assertIn(88, self.runtime.state.input_scope.managed_open_status)
            self.assertEqual(self.win.imm32.set_open_calls[-1], False)

            self.win.imm32.open_status = False
            self.assertTrue(self.ime_switch.restore_if_managed(88))

        self.assertEqual(self.win.imm32.set_open_calls[-1], True)
        self.assertEqual(self.win.imm32.set_conversion_calls[-1], (7, 9))
        self.assertNotIn(88, self.runtime.state.input_scope.managed_open_status)

    def test_restore_does_not_open_ime_that_was_originally_closed(self) -> None:
        self.win.imm32.open_status = False
        with patched(self.ime_switch.platform_api, "ensure", lambda: self.win):
            self.assertTrue(self.ime_switch.close_for_shortcut_surface(99))
            self.assertTrue(self.ime_switch.restore_if_managed(99))
        self.assertEqual(self.win.imm32.set_open_calls, [False])


if __name__ == "__main__":
    unittest.main()
