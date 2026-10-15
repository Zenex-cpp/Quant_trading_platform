from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from trading_platform.v429.external_file_safety import (
    ExternalFileSafetyErrorV429,
    read_external_regular_file_v429,
    resolve_external_output_v429,
    write_external_new_file_v429,
)


def test_v429_external_reader_reads_regular_bounded_file_and_returns_opened_metadata(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    review = tmp_path / "review"
    review.mkdir(mode=0o700)
    item = review / "evidence.json"
    item.write_text('{"snapshot":true}', encoding="utf-8")

    path, payload, metadata = read_external_regular_file_v429(
        root, item, label="EVIDENCE", max_bytes=128
    )
    assert path == item
    assert payload == b'{"snapshot":true}'
    assert stat.S_ISREG(metadata.st_mode)


def test_v429_external_reader_rejects_input_inside_repository(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    item = root / "evidence.json"
    item.write_text("{}", encoding="utf-8")
    with pytest.raises(ExternalFileSafetyErrorV429, match="OUTSIDE_REPOSITORY"):
        read_external_regular_file_v429(root, item, label="EVIDENCE", max_bytes=128)


@pytest.mark.parametrize("raw", ["../private.pem", "review/../private.pem", "C:\\keys\\review.pem", "//server/share/key.pem", ""])
def test_v429_external_reader_rejects_traversal_and_non_posix_paths(tmp_path: Path, raw: str):
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(ExternalFileSafetyErrorV429):
        read_external_regular_file_v429(root, raw, label="KEY", max_bytes=128)


def test_v429_external_reader_rejects_symlinked_parent_and_final_symlink(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    real = tmp_path / "real"
    real.mkdir()
    target = real / "key.pem"
    target.write_text("private", encoding="utf-8")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    final_link = tmp_path / "key-link.pem"
    final_link.symlink_to(target)

    with pytest.raises(ExternalFileSafetyErrorV429, match="PARENT_COMPONENT_UNSAFE"):
        read_external_regular_file_v429(root, alias / "key.pem", label="KEY", max_bytes=128)
    with pytest.raises(ExternalFileSafetyErrorV429, match="OPEN_FAILED_OR_SYMLINK"):
        read_external_regular_file_v429(root, final_link, label="KEY", max_bytes=128)


def test_v429_external_reader_rejects_non_regular_and_oversized_files(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    too_large = external / "large.bin"
    too_large.write_bytes(b"x" * 20)
    with pytest.raises(ExternalFileSafetyErrorV429, match="SIZE_LIMIT"):
        read_external_regular_file_v429(root, too_large, label="EVIDENCE", max_bytes=10)

    fifo = external / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(ExternalFileSafetyErrorV429, match="OPEN_FAILED_OR_SYMLINK|NOT_REGULAR_FILE"):
        read_external_regular_file_v429(root, fifo, label="EVIDENCE", max_bytes=128)


def test_v429_output_rejects_symlinked_parent_before_creating_file(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    alias_parent = tmp_path / "parent-link"
    alias_parent.symlink_to(real_parent, target_is_directory=True)
    key = tmp_path / "key.pem"
    key.write_text("key", encoding="utf-8")

    with pytest.raises(ExternalFileSafetyErrorV429, match="PARENT_COMPONENT_UNSAFE"):
        resolve_external_output_v429(
            root, alias_parent / "signed.json", label="SIGNED",
            protected_inputs={"private_key": key},
        )
    assert not (real_parent / "signed.json").exists()


def test_v429_output_is_exclusive_mode_0600_and_never_overwrites(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir(mode=0o700)
    key = external / "key.pem"
    key.write_text("key", encoding="utf-8")
    target = external / "signed.json"

    result = write_external_new_file_v429(
        root, target, '{"signed":true}\n', label="SIGNED",
        protected_inputs={"private_key": key},
    )
    assert result == target
    assert target.read_text(encoding="utf-8") == '{"signed":true}\n'
    assert stat.S_IMODE(target.stat().st_mode) == 0o600

    with pytest.raises(ExternalFileSafetyErrorV429, match="OUTPUT_ALREADY_EXISTS|CREATE_FAILED_OR_ALREADY_EXISTS"):
        write_external_new_file_v429(
            root, target, '{"tampered":true}\n', label="SIGNED",
            protected_inputs={"private_key": key},
        )
    assert target.read_text(encoding="utf-8") == '{"signed":true}\n'


def test_v429_output_rejects_existing_target_hardlinked_to_protected_input(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    key = external / "key.pem"
    key.write_text("secret", encoding="utf-8")
    alias = external / "output.json"
    os.link(key, alias)
    with pytest.raises(ExternalFileSafetyErrorV429, match="OUTPUT_ALREADY_EXISTS|OUTPUT_OVERWRITES_PRIVATE_KEY"):
        resolve_external_output_v429(
            root, alias, label="SIGNED", protected_inputs={"private_key": key}
        )
    assert key.read_text(encoding="utf-8") == "secret"


def test_v429_output_refuses_unavailable_parent_race_primitives(monkeypatch, tmp_path: Path):
    # Strict mode must fail closed rather than silently fall back to path-based I/O.
    from trading_platform.v429 import external_file_safety as module
    monkeypatch.setattr(module, "os", type("FakeOS", (), {"name": "nt"})())
    with pytest.raises(ExternalFileSafetyErrorV429, match="UNSUPPORTED"):
        module.resolve_external_output_v429(tmp_path / "repo", tmp_path / "out.json", label="SIGNED", protected_inputs={})


def test_v429_output_revalidates_parent_chain_after_preflight(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    parent = tmp_path / "external-parent"
    parent.mkdir()
    protected = tmp_path / "key.pem"
    protected.write_text("key", encoding="utf-8")
    candidate = parent / "signed.json"
    validated = resolve_external_output_v429(
        root, candidate, label="SIGNED", protected_inputs={"private_key": protected}
    )
    assert validated == candidate

    moved = tmp_path / "moved-parent"
    parent.rename(moved)
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    parent.symlink_to(attacker, target_is_directory=True)
    with pytest.raises(ExternalFileSafetyErrorV429, match="PARENT_COMPONENT_UNSAFE"):
        write_external_new_file_v429(
            root, candidate, '{"signed":true}\n', label="SIGNED",
            protected_inputs={"private_key": protected},
        )
    assert not (attacker / "signed.json").exists()
    assert not (moved / "signed.json").exists()
