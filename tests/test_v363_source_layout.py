from pathlib import Path
import tomllib


def test_src_layout_is_canonical():
    root = Path(".")
    assert (root / "src/trading_platform/__init__.py").is_file()
    assert not (root / "trading_platform").exists()


def test_setuptools_discovery_points_to_src():
    project = tomllib.loads(Path("pyproject.toml").read_text())
    assert project["tool"]["setuptools"]["package-dir"]["" ] == "src"
    assert project["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]


def test_runtime_import_resolves_from_src():
    import trading_platform
    source = Path(trading_platform.__file__).resolve()
    assert "src/trading_platform" in source.as_posix()
