from __future__ import annotations

from pathlib import Path
import sys

DEFAULT_FORBIDDEN_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
DEFAULT_FORBIDDEN_SUFFIXES = {".pyc", ".pyo"}


def find_transients(root: Path) -> list[str]:
    offenders: list[str] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if path.is_dir() and path.name in DEFAULT_FORBIDDEN_DIRS:
            offenders.append(relative.as_posix())
            continue
        if path.is_file() and path.suffix in DEFAULT_FORBIDDEN_SUFFIXES:
            if not any(part in DEFAULT_FORBIDDEN_DIRS for part in relative.parts[:-1]):
                offenders.append(relative.as_posix())
    return sorted(set(offenders))


def validate(root: Path) -> list[str]:
    return find_transients(root)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path(args[0]) if args else Path(".")
    root = root.resolve()
    offenders = validate(root)
    if offenders:
        print("RELEASE_HYGIENE=FAIL")
        for item in offenders:
            print(item)
        return 1
    print("RELEASE_HYGIENE=PASS")
    print(f"ROOT={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
