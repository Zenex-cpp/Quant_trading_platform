import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (ROOT / "src", ROOT / "scripts")


def test_platform_sources_parse_with_minimum_supported_python_310():
    failures = []
    for source_root in SOURCE_ROOTS:
        for path in sorted(source_root.rglob("*.py")):
            try:
                ast.parse(
                    path.read_text(encoding="utf-8"),
                    filename=str(path),
                    feature_version=(3, 10),
                )
            except SyntaxError as exc:
                relative = path.relative_to(ROOT).as_posix()
                failures.append(f"{relative}:{exc.lineno}:{exc.msg}")
    assert failures == []
