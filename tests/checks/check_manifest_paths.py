from __future__ import annotations

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "blender_manifest.toml"
EXCLUDED_DIRS = {".git", ".serena", "__pycache__", "tests"}
BLOCKED_BUILD_PREFIXES = (
    ".git/",
    ".serena/",
    "__pycache__/",
    "tests/",
)
BLOCKED_BUILD_NAMES = {
    ".DS_Store",
    "build_extension.bat",
    "build_extension.command",
    "build_extension.sh",
}


def is_blocked_build_path(path: str) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    name = normalized.rsplit("/", 1)[-1]
    if name in BLOCKED_BUILD_NAMES or name.endswith(".pyc"):
        return True
    return any(
        normalized == prefix.rstrip("/") or normalized.startswith(prefix)
        for prefix in BLOCKED_BUILD_PREFIXES
    )


def manifest_paths(root: Path) -> set[str]:
    data = tomllib.loads((root / "blender_manifest.toml").read_text(encoding="utf-8"))
    return set(data.get("build", {}).get("paths", []))


def production_python_paths(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if path.is_file() and not any(
            part in EXCLUDED_DIRS for part in path.relative_to(root).parts
        )
    }


def check_manifest(root: Path = ROOT) -> list[str]:
    paths = manifest_paths(root)
    production_py = production_python_paths(root)

    missing = sorted(production_py - paths)
    stale = sorted(item for item in paths if not (root / item).exists())
    blocked = sorted(item for item in paths if is_blocked_build_path(item))

    messages: list[str] = []
    if missing:
        messages.append("Python files missing from [build].paths:")
        messages.extend(f"  {item}" for item in missing)
    if stale:
        messages.append("Stale paths in [build].paths:")
        messages.extend(f"  {item}" for item in stale)
    if blocked:
        messages.append("Paths that must not be shipped in the extension package:")
        messages.extend(f"  {item}" for item in blocked)
    return messages


def main() -> int:
    messages = check_manifest(ROOT)
    if messages:
        for item in messages:
            print(item)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
