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


class SessionObjC:
    def __init__(self) -> None:
        self.input_context = 20
        self.discard_marked_text = 21
        self.set_marked_text = 22
        self.calls: list[tuple[int, int]] = []

    def object_getClass(self, _obj: int) -> int:
        return 1

    def responds(self, _obj: int, _selector: int) -> bool:
        return True

    def send_void(self, obj: int, selector: int) -> None:
        self.calls.append((obj, selector))


class MacOSTextHookTests(unittest.TestCase):
    def setUp(self) -> None:
        module = import_bridge_module("platforms.macos_text_hook")
        self.module = module
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

    def session_hook(self):
        hook = self.module.MacOSTextInputHookMixin()
        hook._init_text_input_hook()
        hook.objc = SessionObjC()
        hook.text_from_objc_string = lambda value: {
            11: "ce's",
            12: "测试",
        }.get(value, "")
        hook._input_context_records = {
            1: {
                "callable": lambda *_args: 77,
            }
        }
        return hook

    def test_bridge_session_forwards_marked_text_for_candidates(self) -> None:
        hook = self.session_hook()
        forwarded: list[tuple[int, int]] = []
        hook._bridge_owner_callback = lambda: True
        hook._set_marked_text_records = {
            1: {
                "callable": lambda obj, _sel, chars, *_args: forwarded.append(
                    (obj, chars),
                ),
            }
        }

        hook._handle_set_marked_text(
            100,
            0,
            11,
            self.module.NSRange(4, 0),
            self.module.NSRange(0, 0),
        )

        self.assertEqual(forwarded, [(100, 11)])
        self.assertTrue(hook._bridge_session_active)

    def test_bridge_commit_ends_native_marked_text_without_forwarding_insert(self) -> None:
        hook = self.session_hook()
        commits: list[str] = []
        forwarded_insert: list[str] = []
        forwarded_marked: list[tuple[int, int]] = []
        hook._commit_handler = lambda text: commits.append(text) or True
        hook._bridge_owner_callback = lambda: True
        hook._insert_text_records = {
            1: {
                "callable": lambda *_args: forwarded_insert.append("insert"),
            }
        }
        hook._set_marked_text_records = {
            1: {
                "callable": lambda obj, _sel, chars, *_args: forwarded_marked.append(
                    (obj, chars),
                ),
            }
        }

        hook._handle_set_marked_text(
            100,
            0,
            11,
            self.module.NSRange(4, 0),
            self.module.NSRange(0, 0),
        )
        hook._handle_insert_text(100, 0, 12, self.module.NSRange(0, 0))

        self.assertEqual(commits, ["测试"])
        self.assertEqual(forwarded_insert, [])
        self.assertEqual(forwarded_marked, [(100, 11), (100, 0)])
        self.assertFalse(hook._bridge_session_active)
        self.assertEqual(hook.objc.calls, [(77, hook.objc.discard_marked_text)])

    def test_bridge_unmark_ends_native_marked_text_without_discard(self) -> None:
        hook = self.session_hook()
        forwarded_marked: list[tuple[int, int]] = []
        forwarded_unmark: list[int] = []
        hook._bridge_owner_callback = lambda: True
        hook._set_marked_text_records = {
            1: {
                "callable": lambda obj, _sel, chars, *_args: forwarded_marked.append(
                    (obj, chars),
                ),
            }
        }
        hook._unmark_text_records = {
            1: {
                "callable": lambda obj, _sel: forwarded_unmark.append(obj),
            }
        }

        hook._handle_set_marked_text(
            100,
            0,
            11,
            self.module.NSRange(4, 0),
            self.module.NSRange(0, 0),
        )
        hook._handle_unmark_text(100, 0)

        self.assertEqual(forwarded_marked, [(100, 11), (100, 0)])
        self.assertEqual(forwarded_unmark, [])
        self.assertFalse(hook._bridge_session_active)
        self.assertEqual(hook.objc.calls, [])

    def test_unowned_insert_text_forwards_to_blender(self) -> None:
        hook = self.session_hook()
        forwarded: list[tuple[int, int]] = []
        hook._commit_handler = lambda _text: True
        hook._bridge_owner_callback = lambda: False
        hook._insert_text_records = {
            1: {
                "callable": lambda obj, _sel, chars, *_args: forwarded.append(
                    (obj, chars),
                ),
            }
        }

        hook._handle_insert_text(100, 0, 12, self.module.NSRange(0, 0))

        self.assertEqual(forwarded, [(100, 12)])
        self.assertFalse(hook._bridge_session_active)
        self.assertEqual(hook.objc.calls, [])

    def test_unowned_marked_text_forwards_to_blender(self) -> None:
        hook = self.session_hook()
        forwarded: list[tuple[int, int]] = []
        hook._bridge_owner_callback = lambda: False
        hook._set_marked_text_records = {
            1: {
                "callable": lambda obj, _sel, chars, *_args: forwarded.append(
                    (obj, chars),
                ),
            }
        }

        hook._handle_set_marked_text(
            100,
            0,
            11,
            self.module.NSRange(4, 0),
            self.module.NSRange(0, 0),
        )

        self.assertEqual(forwarded, [(100, 11)])
        self.assertFalse(hook._bridge_session_active)


if __name__ == "__main__":
    unittest.main()
