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


def manifest_paths(root: Path = ROOT) -> set[str]:
    """Read the package's required runtime files from blender_manifest.toml."""
    manifest = root / "blender_manifest.toml"
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    return set(data.get("build", {}).get("paths", []))


def package_entries(package: Path) -> list[str]:
    """Return file entries using forward slashes and no surrounding root slash."""
    with zipfile.ZipFile(package) as archive:
        return sorted(
            name.replace("\\", "/").strip("/")
            for name in archive.namelist()
            if name and not name.endswith("/")
        )


def normalized_package_entries(package: Path) -> set[str]:
    """Accept both flat zips and zips wrapped in the extension id directory."""
    entries = set(package_entries(package))
    for name in tuple(entries):
        if "/" in name:
            entries.add(name.split("/", 1)[1])
    return entries


def blocked_entries(package: Path) -> list[str]:
    return sorted(name for name in package_entries(package) if BLOCKED.search(name))


def missing_required_entries(package: Path, root: Path = ROOT) -> list[str]:
    required = {"blender_manifest.toml", *manifest_paths(root)}
    available = normalized_package_entries(package)
    return sorted(required - available)


def check_package(package: Path, root: Path = ROOT) -> list[str]:
    if not package.is_file():
        return [f"package not found: {package}"]
    bad = blocked_entries(package)
    missing = missing_required_entries(package, root)

    messages: list[str] = []
    if bad:
        messages.append("Package contains files that should not be shipped:")
        messages.extend(f"  {item}" for item in bad)
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
