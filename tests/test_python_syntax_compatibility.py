import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (ROOT / "src", ROOT / "scripts")
FSTRING_DELIMITER = re.compile(r"(?i)^[rubf]*([\"'])")


def _compatibility_failures(source: str, filename: str) -> list[str]:
    try:
        tree = ast.parse(source, filename=filename, feature_version=(3, 10))
    except SyntaxError as exc:
        return [f"{filename}:{exc.lineno}:{exc.msg}"]

    failures = []
    for joined in ast.walk(tree):
        if not isinstance(joined, ast.JoinedStr):
            continue
        token = ast.get_source_segment(source, joined)
        delimiter_match = FSTRING_DELIMITER.match(token or "")
        if delimiter_match is None:
            continue
        delimiter = delimiter_match.group(1)
        for field in (node for node in ast.walk(joined) if isinstance(node, ast.FormattedValue)):
            for child in ast.walk(field.value):
                if not isinstance(child, ast.Constant) or not isinstance(child.value, str):
                    continue
                literal = ast.get_source_segment(source, child)
                if literal and literal.startswith(delimiter):
                    failures.append(
                        f"{filename}:{child.lineno}:same-quote string inside f-string expression"
                    )
    return failures


def test_platform_sources_parse_with_minimum_supported_python_310():
    failures = []
    for source_root in SOURCE_ROOTS:
        for path in sorted(source_root.rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            failures.extend(_compatibility_failures(path.read_text(encoding="utf-8"), relative))
    assert failures == []


def test_minimum_version_check_rejects_pep701_same_quote_fstring_expression():
    incompatible = 'assessment_id = f"{json.dumps(payload, separators=(",", ":"))}"'
    assert _compatibility_failures(incompatible, "sample.py")
