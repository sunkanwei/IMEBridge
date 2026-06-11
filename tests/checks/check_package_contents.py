from __future__ import annotations

from pathlib import Path
import re
import sys
import zipfile


BLOCKED = re.compile(
    r"(^|/)(README\.md|build_extension\.(bat|command|sh))$"
    r"|(^|/)(\.git|\.serena|tests)(/|$)"
    r"|(^|/)__pycache__(/|$)"
    r"|\.pyc$"
    r"|(^|/)\.DS_Store$",
    re.IGNORECASE,
)


def blocked_entries(package: Path) -> list[str]:
    with zipfile.ZipFile(package) as archive:
        return sorted(name for name in archive.namelist() if BLOCKED.search(name))


def check_package(package: Path) -> list[str]:
    if not package.is_file():
        return [f"package not found: {package}"]
    bad = blocked_entries(package)
    if not bad:
        return []
    return [
        "Package contains files that should not be shipped:",
        *[f"  {item}" for item in bad],
    ]


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
