from __future__ import annotations

import argparse
import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {".git", ".serena", "__pycache__"}


def run_command(args: list[str], *, cwd: Path = ROOT) -> None:
    print("+", " ".join(str(item) for item in args), flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def compile_sources() -> None:
    for path in sorted(ROOT.rglob("*.py")):
        rel_parts = path.relative_to(ROOT).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            continue
        py_compile.compile(str(path), doraise=True)


def run_unittest() -> None:
    run_command(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-t",
            ".",
            "-p",
            "test_*.py",
        ]
    )


def run_manifest_check() -> None:
    run_command([sys.executable, "tests/checks/check_manifest_paths.py"])


def run_text_hygiene_check() -> None:
    run_command([sys.executable, "tests/checks/check_text_hygiene.py"])


def find_blender(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    env_value = os.environ.get("BLENDER_EXE")
    if env_value:
        return env_value
    relative = (ROOT / ".." / ".." / ".." / ".." / "blender.exe").resolve()
    if relative.exists():
        return str(relative)
    return shutil.which("blender")


def run_blender_validate(blender: str | None) -> None:
    blender_exe = find_blender(blender)
    if not blender_exe:
        raise SystemExit("Blender executable was not found. Set BLENDER_EXE.")
    run_command(
        [
            blender_exe,
            "--factory-startup",
            "--command",
            "extension",
            "validate",
            str(ROOT),
        ]
    )


def run_blender_smoke(blender: str | None) -> None:
    blender_exe = find_blender(blender)
    if not blender_exe:
        raise SystemExit("Blender executable was not found. Set BLENDER_EXE.")
    run_command(
        [
            blender_exe,
            "--factory-startup",
            "--background",
            "--python",
            str(ROOT / "tests" / "blender" / "register_smoke.py"),
        ]
    )


def run_package_check(package: str | None) -> None:
    if not package:
        raise SystemExit("release requires --package PATH_TO_ZIP")
    run_command([sys.executable, "tests/checks/check_package_contents.py", package])


def quick() -> None:
    compile_sources()
    run_unittest()
    run_manifest_check()
    run_text_hygiene_check()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run IMEBridge quality gates.")
    parser.add_argument(
        "profile",
        choices=("quick", "full", "release"),
        nargs="?",
        default="quick",
    )
    parser.add_argument("--blender", help="Path to Blender executable.")
    parser.add_argument("--package", help="Path to built extension zip.")
    args = parser.parse_args()

    quick()
    if args.profile in {"full", "release"}:
        run_blender_validate(args.blender)
        run_blender_smoke(args.blender)
    if args.profile == "release":
        run_package_check(args.package)


if __name__ == "__main__":
    main()
