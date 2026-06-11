import unittest

from tests.support.env import import_bridge_module


class FakeObjC:
    def __init__(self) -> None:
        self.implementations = {10: 100}
        self.previous_results = {10: 101}
        self.calls: list[tuple[int, int]] = []

    def method_getImplementation(self, method: int) -> int:
        return self.implementations.get(method, 0)

    def method_setImplementation(self, method: int, replacement: int) -> int:
        previous = self.previous_results.get(method, self.implementations[method])
        self.implementations[method] = replacement
        self.previous_results[method] = replacement
        self.calls.append((method, replacement))
        return previous


class MacOSTextHookTests(unittest.TestCase):
    def setUp(self) -> None:
        module = import_bridge_module("platforms.macos_text_hook")
        self.hook = module.MacOSTextInputHookMixin()
        self.hook.objc = FakeObjC()

    def test_method_patch_rolls_back_when_record_rebuild_fails(self) -> None:
        def imp_type(value: int) -> object:
            if value == 101:
                raise TypeError("cannot wrap previous imp")
            return lambda *_args: value

        with self.assertRaises(TypeError):
            self.hook._install_method_patch({}, 1, 10, 200, imp_type)

        self.assertEqual(self.hook.objc.implementations[10], 101)
        self.assertEqual(self.hook.objc.calls, [(10, 200), (10, 101)])

    def test_method_patch_does_not_replace_until_initial_record_is_ready(self) -> None:
        def imp_type(_value: int) -> object:
            raise TypeError("cannot wrap old imp")

        with self.assertRaises(TypeError):
            self.hook._install_method_patch({}, 1, 10, 200, imp_type)

        self.assertEqual(self.hook.objc.implementations[10], 100)
        self.assertEqual(self.hook.objc.calls, [])


if __name__ == "__main__":
    unittest.main()
