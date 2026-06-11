import unittest
from types import SimpleNamespace

from tests.support.env import import_bridge_module, patched, reset_runtime


class InputScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_runtime()
        self.input_scope = import_bridge_module("bridge.input_scope")

    def area_hit(self, area_type: str):
        area = SimpleNamespace(type=area_type)
        return self.input_scope.AreaHit(
            window=SimpleNamespace(),
            area=area,
            region=SimpleNamespace(),
            space=SimpleNamespace(),
        )

    def test_client_point_from_lparam_decodes_signed_words(self) -> None:
        lparam = (0xFFFE << 16) | 0x0003
        self.assertEqual(self.input_scope.client_point_from_lparam(lparam), (3, -2))

    def test_classify_hit_prioritizes_nexus_neutral(self) -> None:
        hit = self.area_hit("VIEW_3D")
        with patched(self.input_scope.nexus_whitelist, "is_nexusui_surface_hit", lambda _hit: True):
            scope = self.input_scope.classify_hit(1, hit)
        self.assertEqual(scope.kind, self.input_scope.SCOPE_NEUTRAL)

    def test_classify_hit_promotes_text_editor_target(self) -> None:
        hit = self.area_hit("TEXT_EDITOR")
        target = object()
        with patched(
            self.input_scope.nexus_whitelist,
            "is_nexusui_surface_hit",
            lambda _hit: False,
        ):
            with patched(
                self.input_scope.targets,
                "make_text_editor_target",
                lambda *_args: target,
            ):
                scope = self.input_scope.classify_hit(2, hit)
        self.assertEqual(scope.kind, self.input_scope.SCOPE_ENABLED_TARGET)
        self.assertIs(scope.target, target)

    def test_classify_hit_marks_shortcut_canvas_when_no_supported_target_exists(self) -> None:
        hit = self.area_hit("NODE_EDITOR")
        with patched(
            self.input_scope.nexus_whitelist,
            "is_nexusui_surface_hit",
            lambda _hit: False,
        ):
            scope = self.input_scope.classify_hit(3, hit)
        self.assertEqual(scope.kind, self.input_scope.SCOPE_SHORTCUT_SURFACE)


if __name__ == "__main__":
    unittest.main()
