"""Fail-closed path policy for governance scripts.

Repository-relative inputs must remain inside the checkout and may not traverse
symlinks. CLI-generated audit outputs are restricted to `.audit/` and may not
collide with any input. The independent signing tool uses a separate helper for
external outputs and rejects input/key overwrite and symlink destinations.
"""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
from typing import Mapping


class PathSafetyErrorV428(ValueError):
    __test__ = False


def _raw_relative_path(raw_path: str | os.PathLike[str], *, label: str) -> Path:
    raw = os.fspath(raw_path)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise PathSafetyErrorV428(f"{label}_PATH_INVALID")
    win = PureWindowsPath(raw)
    path = Path(raw)
    if path.is_absolute() or win.is_absolute() or bool(win.drive) or raw.startswith(("\\\\", "//")):
        raise PathSafetyErrorV428(f"{label}_ABSOLUTE_PATH_NOT_ALLOWED")
    if any(part == ".." for part in path.parts):
        raise PathSafetyErrorV428(f"{label}_PATH_TRAVERSAL_REJECTED")
    if not path.parts or all(part in {"", "."} for part in path.parts):
        raise PathSafetyErrorV428(f"{label}_PATH_REQUIRED")
    return path


def resolve_repository_path_v428(
    root: str | os.PathLike[str],
    raw_path: str | os.PathLike[str],
    *,
    label: str,
    must_exist_file: bool = False,
    output_scope: str | None = None,
) -> Path:
    """Resolve a repository-relative path while rejecting traversal/symlinks.

    `output_scope='.audit'` requires the output to be below the audit directory.
    Resolution checks all existing path components, including broken symlinks.
    """
    base = Path(root).resolve(strict=True)
    relative = _raw_relative_path(raw_path, label=label)
    candidate = base / relative

    cursor = base
    for component in relative.parts:
        if component in {"", "."}:
            continue
        cursor = cursor / component
        if cursor.is_symlink():
            raise PathSafetyErrorV428(f"{label}_SYMLINK_PATH_REJECTED")

    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(base) or resolved == base:
        raise PathSafetyErrorV428(f"{label}_PATH_OUTSIDE_REPOSITORY")

    if output_scope is not None:
        scope_relative = _raw_relative_path(output_scope, label=f"{label}_OUTPUT_SCOPE")
        scope = (base / scope_relative).resolve(strict=False)
        if not scope.is_relative_to(base) or not resolved.is_relative_to(scope) or resolved == scope:
            raise PathSafetyErrorV428(f"{label}_OUTPUT_SCOPE_VIOLATION")

    if output_scope is not None and resolved.exists() and not resolved.is_file():
        raise PathSafetyErrorV428(f"{label}_OUTPUT_NOT_REGULAR_FILE")
    if must_exist_file and not resolved.is_file():
        raise PathSafetyErrorV428(f"{label}_FILE_NOT_FOUND")
    return resolved


def ensure_paths_distinct_v428(
    *,
    outputs: Mapping[str, Path],
    protected_inputs: Mapping[str, Path],
) -> None:
    """Reject output-output and output-input path collisions, including hardlinks."""
    seen: dict[str, str] = {}
    resolved_outputs: list[tuple[str, Path]] = []
    for label, path in outputs.items():
        normalized = path.resolve(strict=False)
        if normalized in seen:
            raise PathSafetyErrorV428(f"OUTPUT_PATH_COLLISION:{seen[normalized]}:{label}")
        for prior_label, prior_path in resolved_outputs:
            if normalized.exists() and prior_path.exists():
                try:
                    if os.path.samefile(normalized, prior_path):
                        raise PathSafetyErrorV428(f"OUTPUT_PATH_COLLISION:{prior_label}:{label}")
                except OSError:
                    pass
        for input_label, input_path in protected_inputs.items():
            protected = input_path.resolve(strict=False)
            same = normalized == protected
            if not same and normalized.exists() and protected.exists():
                try:
                    same = os.path.samefile(normalized, protected)
                except OSError:
                    same = False
            if same:
                raise PathSafetyErrorV428(f"OUTPUT_OVERWRITES_INPUT:{label}:{input_label}")
        seen[normalized] = label
        resolved_outputs.append((label, normalized))


def resolve_external_output_v428(
    root: str | os.PathLike[str],
    raw_path: str | os.PathLike[str],
    *,
    label: str,
    protected_inputs: Mapping[str, Path],
) -> Path:
    """Resolve a reviewer-side output outside the repository without clobbering inputs."""
    raw = os.fspath(raw_path)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise PathSafetyErrorV428(f"{label}_PATH_INVALID")
    lexical = Path(raw).expanduser()
    if lexical.is_symlink():
        raise PathSafetyErrorV428(f"{label}_SYMLINK_DESTINATION_REJECTED")
    resolved = lexical.resolve(strict=False)
    base = Path(root).resolve(strict=True)
    if resolved.is_relative_to(base):
        raise PathSafetyErrorV428(f"{label}_MUST_BE_OUTSIDE_REPOSITORY")
    if resolved.exists() and not resolved.is_file():
        raise PathSafetyErrorV428(f"{label}_OUTPUT_NOT_REGULAR_FILE")
    for input_label, input_path in protected_inputs.items():
        protected = input_path.resolve(strict=False)
        same = resolved == protected
        if not same and resolved.exists() and protected.exists():
            try:
                same = os.path.samefile(resolved, protected)
            except OSError:
                same = False
        if same:
            raise PathSafetyErrorV428(f"{label}_OUTPUT_OVERWRITES_{input_label.upper()}")
    return resolved


def write_audit_text_v428(root: str | os.PathLike[str], path: Path, text: str) -> None:
    """Avoid following symlinks while writing a `.audit/` file.

    Directory traversal is performed with directory file descriptors and
    O_NOFOLLOW where available, so an existing symlink cannot redirect writes.
    """
    base = Path(root).resolve(strict=True)
    try:
        relative = Path(path).absolute().relative_to(base)
    except ValueError:
        raise PathSafetyErrorV428("AUDIT_WRITE_PATH_OUTSIDE_REPOSITORY") from None
    checked = resolve_repository_path_v428(base, relative.as_posix(), label="AUDIT_WRITE", output_scope=".audit")
    parts = checked.relative_to(base).parts
    if len(parts) < 2 or parts[0] != ".audit":
        raise PathSafetyErrorV428("AUDIT_WRITE_OUTPUT_SCOPE_VIOLATION")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    current_fd = os.open(str(base), directory_flags)
    try:
        for component in parts[:-1]:
            try:
                os.mkdir(component, mode=0o700, dir_fd=current_fd)
            except FileExistsError:
                pass
            next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        fd = os.open(parts[-1], file_flags, 0o600, dir_fd=current_fd)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    except OSError as exc:
        raise PathSafetyErrorV428("AUDIT_WRITE_FAILED_OR_SYMLINK_REJECTED") from None
    finally:
        os.close(current_fd)


def write_external_text_v428(path: Path, text: str) -> None:
    """Write reviewer-side output without following a final symlink."""
    target = Path(path)
    if target.is_symlink():
        raise PathSafetyErrorV428("EXTERNAL_OUTPUT_SYMLINK_DESTINATION_REJECTED")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise PathSafetyErrorV428("EXTERNAL_OUTPUT_DESTINATION_INVALID")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(target), flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    except OSError:
        raise PathSafetyErrorV428("EXTERNAL_OUTPUT_WRITE_FAILED_OR_SYMLINK_REJECTED") from None
