from __future__ import annotations

from pathlib import Path
import re
import sys
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[2]
BLOCKED = re.compile(
    r"(^|/)(README\.md|build_extension\.(bat|command|sh))$"
    r"|(^|/)(\.git|\.serena|tests)(/|$)"
    r"|(^|/)__pycache__(/|$)"
    r"|\.pyc$"
    r"|(^|/)\.DS_Store$",
    re.IGNORECASE,
)


def manifest_data(root: Path = ROOT) -> dict[str, object]:
    """Read blender_manifest.toml as structured data."""
    manifest = root / "blender_manifest.toml"
    return tomllib.loads(manifest.read_text(encoding="utf-8"))


def manifest_paths(root: Path = ROOT) -> set[str]:
    """Read the package's required runtime files from blender_manifest.toml."""
    data = manifest_data(root)
    return set(data.get("build", {}).get("paths", []))


def manifest_extension_id(root: Path = ROOT) -> str | None:
    """Read the extension id used by Blender's extension package wrapper."""
    data = manifest_data(root)
    value = data.get("id")
    return value if isinstance(value, str) and value else None


def package_entries(package: Path) -> list[str]:
    """Return file entries using forward slashes and no surrounding root slash."""
    with zipfile.ZipFile(package) as archive:
        return sorted(
            name.replace("\\", "/").strip("/")
            for name in archive.namelist()
            if name and not name.endswith("/")
        )


def normalized_package_entries(package: Path, root: Path = ROOT) -> set[str]:
    """Accept flat zips, or a zip wholly wrapped in one directory."""
    entries = set(package_entries(package))
    if "blender_manifest.toml" in entries:
        return entries

    prefixes = {name.split("/", 1)[0] for name in entries if "/" in name}
    if len(prefixes) == 1 and all("/" in name for name in entries):
        prefix = next(iter(prefixes))
        expected = manifest_extension_id(root)
        if expected is not None and prefix != expected:
            return entries
        return {name.split("/", 1)[1] for name in entries}
    return entries


def package_layout_messages(package: Path, root: Path = ROOT) -> list[str]:
    """Reject packages that can only pass by combining unrelated top-level dirs."""
    entries = package_entries(package)
    if not entries or "blender_manifest.toml" in entries:
        return []

    root_entries = [name for name in entries if "/" not in name]
    if root_entries:
        return []

    prefixes = {name.split("/", 1)[0] for name in entries if "/" in name}
    if len(prefixes) != 1:
        return [
            "Package root layout is invalid:",
            "  expected a flat package or one top-level extension directory",
        ]

    prefix = next(iter(prefixes))
    expected = manifest_extension_id(root)
    if expected is not None and prefix != expected:
        return [
            "Package wrapper directory does not match the extension id:",
            f"  expected {expected}/, found {prefix}/",
        ]
    return []


def blocked_entries(package: Path) -> list[str]:
    return sorted(name for name in package_entries(package) if BLOCKED.search(name))


def missing_required_entries(package: Path, root: Path = ROOT) -> list[str]:
    required = {"blender_manifest.toml", *manifest_paths(root)}
    available = normalized_package_entries(package, root)
    return sorted(required - available)


def check_package(package: Path, root: Path = ROOT) -> list[str]:
    if not package.is_file():
        return [f"package not found: {package}"]
    bad = blocked_entries(package)
    layout = package_layout_messages(package, root)
    missing = [] if layout else missing_required_entries(package, root)

    messages: list[str] = []
    if bad:
        messages.append("Package contains files that should not be shipped:")
        messages.extend(f"  {item}" for item in bad)
    messages.extend(layout)
    if missing:
        messages.append("Package is missing files required by [build].paths:")
        messages.extend(f"  {item}" for item in missing)
    return messages


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_package_contents.py PATH_TO_ZIP")
        return 2

    messages = check_package(Path(argv[1]))
    if messages:
        for item in messages:
            print(item)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
