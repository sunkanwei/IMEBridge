from pathlib import Path
import tempfile
import unittest
import zipfile

from tests.support.env import import_bridge_module


class GateCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest_check = import_bridge_module("tests.checks.check_manifest_paths")
        self.package_check = import_bridge_module("tests.checks.check_package_contents")
        self.hygiene_check = import_bridge_module("tests.checks.check_text_hygiene")

    def test_manifest_check_reports_missing_stale_and_blocked_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "core").mkdir()
            (root / "core" / "runtime.py").write_text("value = 1\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_runtime.py").write_text("", encoding="utf-8")
            (root / "blender_manifest.toml").write_text(
                '\n'.join(
                    [
                        'schema_version = "1.0.0"',
                        '[build]',
                        'paths = ["missing.py", "tests/test_runtime.py"]',
                    ]
                ),
                encoding="utf-8",
            )

            messages = "\n".join(self.manifest_check.check_manifest(root))

        self.assertIn("core/runtime.py", messages)
        self.assertIn("missing.py", messages)
        self.assertIn("tests/test_runtime.py", messages)

    def test_manifest_check_accepts_production_paths_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "core").mkdir()
            (root / "core" / "runtime.py").write_text("value = 1\n", encoding="utf-8")
            (root / "blender_manifest.toml").write_text(
                '\n'.join(
                    [
                        'schema_version = "1.0.0"',
                        '[build]',
                        'paths = ["core/runtime.py"]',
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(self.manifest_check.check_manifest(root), [])

    def test_package_check_rejects_test_and_local_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "IMEBridge-0.1.0.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("IMEBridge/__init__.py", "")
                archive.writestr("IMEBridge/tests/test_runtime.py", "")
                archive.writestr("IMEBridge/build_extension.bat", "")

            messages = "\n".join(self.package_check.check_package(package))

        self.assertIn("tests/test_runtime.py", messages)
        self.assertIn("build_extension.bat", messages)

    def test_package_check_requires_manifest_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "blender_manifest.toml").write_text(
                '\n'.join(
                    [
                        'schema_version = "1.0.0"',
                        '[build]',
                        'paths = ["__init__.py", "core/runtime.py"]',
                    ]
                ),
                encoding="utf-8",
            )
            package = root / "IMEBridge-0.2.0.zip"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("IMEBridge/blender_manifest.toml", "")
                archive.writestr("IMEBridge/__init__.py", "")

            messages = "\n".join(self.package_check.check_package(package, root))

        self.assertIn("core/runtime.py", messages)

    def test_text_hygiene_reports_common_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "module.py").write_text(
                "value = 1  \n<<<<<<< ours\n",
                encoding="utf-8",
            )

            messages = "\n".join(self.hygiene_check.check_tree(root))

        self.assertIn("trailing whitespace", messages)
        self.assertIn("conflict marker", messages)

    def test_text_hygiene_allows_markdown_setext_heading(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "note.md").write_text(
                "Heading\n=======\n",
                encoding="utf-8",
            )

            self.assertEqual(self.hygiene_check.check_tree(root), [])


if __name__ == "__main__":
    unittest.main()
