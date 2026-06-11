from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKED_SUFFIXES = {".py", ".md", ".toml", ".gitignore", ".gitattributes"}
EXCLUDED_DIRS = {".git", ".serena", "__pycache__"}
CONFLICT_START = "<<<<<<< "
CONFLICT_MIDDLE = "======="
CONFLICT_END = ">>>>>>> "


def is_conflict_marker(line: str, path: Path) -> bool:
    middle_marker = line == CONFLICT_MIDDLE and path.suffix != ".md"
    return (
        line.startswith(CONFLICT_START)
        or middle_marker
        or line.startswith(CONFLICT_END)
    )


def should_check(path: Path, root: Path) -> bool:
    rel_parts = path.relative_to(root).parts
    if any(part in EXCLUDED_DIRS for part in rel_parts):
        return False
    return path.suffix in CHECKED_SUFFIXES or path.name in CHECKED_SUFFIXES


def check_file(path: Path, root: Path) -> list[str]:
    messages: list[str] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.rstrip(" \t") != line:
            messages.append(f"{path.relative_to(root)}:{line_no}: trailing whitespace")
        if is_conflict_marker(line, path):
            messages.append(f"{path.relative_to(root)}:{line_no}: conflict marker")
        if path.suffix == ".py" and line.startswith("\t"):
            messages.append(f"{path.relative_to(root)}:{line_no}: tab indentation")
    return messages


def check_tree(root: Path = ROOT) -> list[str]:
    messages: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and should_check(path, root):
            messages.extend(check_file(path, root))
    return messages


def main() -> int:
    messages = check_tree(ROOT)
    if messages:
        for item in messages:
            print(item)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
