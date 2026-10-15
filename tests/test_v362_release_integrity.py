from pathlib import Path
import tomllib

from trading_platform import __version__
from trading_platform.verification.acceptance import AcceptanceItem, AcceptanceStatus, build_acceptance


def test_acceptance_success_does_not_equal_production_readiness():
    report = build_acceptance([
        AcceptanceItem("A", AcceptanceStatus.PASS, "E-A", True),
        AcceptanceItem("B", AcceptanceStatus.PASS, "E-B", True),
    ])
    assert report.acceptance_passed is True
    assert report.production_ready is False


def test_project_version_matches_runtime_version():
    project = tomllib.loads(Path("pyproject.toml").read_text())
    assert project["project"]["version"] == __version__ == "3.61.0"


def test_source_of_truth_document_exists():
    doc = Path("docs/00_REPOSITORY_SOURCE_OF_TRUTH.md")
    assert doc.is_file()
    assert "`src/trading_platform/`" in doc.read_text()
    assert not Path("trading_platform").is_dir()
