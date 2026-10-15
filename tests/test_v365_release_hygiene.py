from pathlib import Path

from trading_platform import __version__
from scripts.validate_release_hygiene import validate


def test_release_hygiene_detects_forbidden_transient(tmp_path):
    cache = tmp_path / "module" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "x.pyc").write_bytes(b"x")
    assert validate(tmp_path) == ["module/__pycache__"]


def test_release_hygiene_detects_bytecode_file(tmp_path):
    (tmp_path / "x.pyc").write_bytes(b"x")
    assert validate(tmp_path) == ["x.pyc"]


def test_python_package_version_contract_is_preserved():
    assert __version__ == "3.61.0"
