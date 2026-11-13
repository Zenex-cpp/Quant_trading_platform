from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_v5_repository_map_matches_all_top_level_runtime_and_test_directories():
    with (ROOT / "schemas/v5_repository_structure.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        rows = list(csv.DictReader(stream))

    assert rows and all(row["path"].strip() and row["purpose"].strip() for row in rows)
    assert len({(row["scope"], row["path"]) for row in rows}) == len(rows)
    by_scope: dict[str, set[str]] = {}
    for row in rows:
        by_scope.setdefault(row["scope"], set()).add(row["path"])

    actual_root_dirs = {
        path.name for path in ROOT.iterdir()
        if path.is_dir() and path.name not in {".git", ".audit"}
    }
    assert by_scope["ROOT_DIRECTORY"] | by_scope["LEGACY_ROOT_DIRECTORY"] == actual_root_dirs

    runtime_root = ROOT / "src/trading_platform"
    actual_runtime_dirs = {path.name for path in runtime_root.iterdir() if path.is_dir()}
    mapped_runtime_dirs = {
        path.removeprefix("src/trading_platform/")
        for scope in ("RUNTIME_DOMAIN", "RUNTIME_VERSION")
        for path in by_scope[scope]
    }
    assert mapped_runtime_dirs == actual_runtime_dirs

    actual_test_groups = {path.name for path in (ROOT / "tests").iterdir() if path.is_dir()}
    mapped_test_groups = {
        path.removeprefix("tests/") for path in by_scope["TEST_GROUP"]
    }
    assert mapped_test_groups == actual_test_groups
    assert len(actual_root_dirs) == 21
    assert len(actual_runtime_dirs) == 148
    assert len(actual_test_groups) == 87

    assert not (ROOT / "trading_platform").is_dir()
    assert (ROOT / "src/trading_platform/__init__.py").is_file()
    assert len(by_scope["ROOT_FILE_FAMILY"]) == 6


def test_v5_repository_map_documents_the_canonical_source_and_audit_boundary():
    document = (ROOT / "docs/66_V5_REPOSITORY_STRUCTURE.md").read_text(encoding="utf-8")
    source_of_truth = (ROOT / "docs/00_REPOSITORY_SOURCE_OF_TRUTH.md").read_text(
        encoding="utf-8"
    )
    assert "all 148 direct runtime namespaces" in document
    assert "all 87 direct test groups" in document
    assert "`.audit/` holds local milestone reports" in document
    assert "docs/66_V5_REPOSITORY_STRUCTURE.md" in source_of_truth
