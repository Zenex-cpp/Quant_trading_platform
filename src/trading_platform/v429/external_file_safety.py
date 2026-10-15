"""Race-resistant filesystem access for independent governance signing.

Only POSIX systems with openat/O_NOFOLLOW semantics are supported for strict
reviewer-side file access. Existing symlink components are rejected; inputs
are opened through directory file descriptors, bounded and fstat-checked. New
outputs are created exclusively and are never overwritten.
"""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
import stat
from typing import Mapping


class ExternalFileSafetyErrorV429(ValueError):
    __test__ = False


def _require_strict_posix_v429() -> None:
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ExternalFileSafetyErrorV429("STRICT_EXTERNAL_FILE_ACCESS_UNSUPPORTED_ON_THIS_PLATFORM")


def _absolute_lexical_path_v429(raw_path: str | os.PathLike[str], *, label: str) -> Path:
    raw = os.fspath(raw_path)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ExternalFileSafetyErrorV429(f"{label}_PATH_INVALID")
    win = PureWindowsPath(raw)
    if win.drive or raw.startswith(("\\\\", "//")):
        raise ExternalFileSafetyErrorV429(f"{label}_WINDOWS_OR_UNC_PATH_REJECTED")
    # Do not normalize traversal away before inspecting it.
    if ".." in raw.replace("\\", "/").split("/"):
        raise ExternalFileSafetyErrorV429(f"{label}_PATH_TRAVERSAL_REJECTED")
    lexical = Path(raw).expanduser()
    if not lexical.is_absolute():
        lexical = Path.cwd() / lexical
    # Path.absolute/abspath normalizes '.', but traversal was rejected above.
    absolute = Path(os.path.abspath(os.fspath(lexical)))
    if not absolute.is_absolute() or absolute == Path("/") or not absolute.name:
        raise ExternalFileSafetyErrorV429(f"{label}_PATH_INVALID")
    return absolute


def _open_parent_chain_v429(path: Path, *, create_missing: bool) -> int:
    """Return an fd for `path.parent`, rejecting symlinks at every component."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fd = os.open("/", flags)
    try:
        for component in path.parent.parts[1:]:
            try:
                next_fd = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create_missing:
                    raise ExternalFileSafetyErrorV429("EXTERNAL_PARENT_DIRECTORY_MISSING") from None
                try:
                    os.mkdir(component, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    # Another process created it; the no-follow open below
                    # verifies it is an ordinary directory, not a symlink.
                    pass
                try:
                    next_fd = os.open(component, flags, dir_fd=fd)
                except OSError:
                    raise ExternalFileSafetyErrorV429("EXTERNAL_PARENT_COMPONENT_UNSAFE") from None
            except OSError:
                raise ExternalFileSafetyErrorV429("EXTERNAL_PARENT_COMPONENT_UNSAFE") from None
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def _ensure_outside_root_v429(path: Path, root: str | os.PathLike[str], label: str) -> None:
    base = Path(root).resolve(strict=True)
    # All parent components are later opened without following symlinks, so
    # lexical containment is sufficient and does not silently resolve links.
    if path == base or path.is_relative_to(base):
        raise ExternalFileSafetyErrorV429(f"{label}_PATH_MUST_BE_OUTSIDE_REPOSITORY")


def read_external_regular_file_v429(
    root: str | os.PathLike[str],
    raw_path: str | os.PathLike[str],
    *,
    label: str,
    max_bytes: int,
) -> tuple[Path, bytes, os.stat_result]:
    """Read one external regular file without following path symlinks.

    The file is opened via a directory fd, bounded by `max_bytes`, and checked
    for size/mtime/inode changes before and after reading.
    """
    _require_strict_posix_v429()
    if not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ExternalFileSafetyErrorV429("FILE_SIZE_LIMIT_INVALID")
    path = _absolute_lexical_path_v429(raw_path, label=label)
    _ensure_outside_root_v429(path, root, label)
    parent_fd = _open_parent_chain_v429(path, create_missing=False)
    fd = -1
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(path.name, flags, dir_fd=parent_fd)
        except OSError:
            raise ExternalFileSafetyErrorV429(f"{label}_OPEN_FAILED_OR_SYMLINK_REJECTED") from None
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ExternalFileSafetyErrorV429(f"{label}_NOT_REGULAR_FILE")
        if before.st_size < 0 or before.st_size > max_bytes:
            raise ExternalFileSafetyErrorV429(f"{label}_FILE_SIZE_LIMIT_EXCEEDED")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise ExternalFileSafetyErrorV429(f"{label}_FILE_SIZE_LIMIT_EXCEEDED")
        after = os.fstat(fd)
        if (total != before.st_size or after.st_size != before.st_size
                or after.st_dev != before.st_dev or after.st_ino != before.st_ino
                or after.st_mtime_ns != before.st_mtime_ns
                or after.st_ctime_ns != before.st_ctime_ns):
            raise ExternalFileSafetyErrorV429(f"{label}_FILE_CHANGED_DURING_READ")
        return path, b"".join(chunks), before
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(parent_fd)


def resolve_external_output_v429(
    root: str | os.PathLike[str],
    raw_path: str | os.PathLike[str],
    *,
    label: str,
    protected_inputs: Mapping[str, Path],
) -> Path:
    """Validate a future external output path; no existing file is overwritten."""
    _require_strict_posix_v429()
    path = _absolute_lexical_path_v429(raw_path, label=label)
    _ensure_outside_root_v429(path, root, label)
    parent_fd = _open_parent_chain_v429(path, create_missing=True)
    try:
        try:
            existing = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        except OSError:
            raise ExternalFileSafetyErrorV429(f"{label}_DESTINATION_STATUS_FAILED") from None
        if existing is not None:
            raise ExternalFileSafetyErrorV429(f"{label}_OUTPUT_ALREADY_EXISTS")
    finally:
        os.close(parent_fd)
    for input_label, input_path in protected_inputs.items():
        protected = Path(input_path)
        if path == protected:
            raise ExternalFileSafetyErrorV429(f"{label}_OUTPUT_OVERWRITES_{input_label.upper()}")
        try:
            if path.exists() and protected.exists() and os.path.samefile(path, protected):
                raise ExternalFileSafetyErrorV429(f"{label}_OUTPUT_OVERWRITES_{input_label.upper()}")
        except OSError:
            raise ExternalFileSafetyErrorV429(f"{label}_INPUT_ALIAS_CHECK_FAILED") from None
    return path


def write_external_new_file_v429(
    root: str | os.PathLike[str],
    raw_path: str | os.PathLike[str],
    text: str,
    *,
    label: str,
    protected_inputs: Mapping[str, Path],
    mode: int = 0o600,
) -> Path:
    """Create a new external output using openat and O_EXCL; never overwrite."""
    _require_strict_posix_v429()
    path = resolve_external_output_v429(root, raw_path, label=label, protected_inputs=protected_inputs)
    parent_fd = _open_parent_chain_v429(path, create_missing=True)
    fd = -1
    created_stat: os.stat_result | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(path.name, flags, mode, dir_fd=parent_fd)
        except OSError:
            raise ExternalFileSafetyErrorV429(f"{label}_OUTPUT_CREATE_FAILED_OR_ALREADY_EXISTS") from None
        created_stat = os.fstat(fd)
        if not stat.S_ISREG(created_stat.st_mode):
            raise ExternalFileSafetyErrorV429(f"{label}_OUTPUT_NOT_REGULAR_FILE")
        data = text.encode("utf-8")
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise ExternalFileSafetyErrorV429(f"{label}_OUTPUT_WRITE_FAILED")
            view = view[written:]
        os.fsync(fd)
        return path
    except Exception:
        # Delete only the file created by this operation, and only if the
        # directory entry still references the same inode.
        if fd >= 0 and created_stat is not None:
            try:
                current = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
                opened = os.fstat(fd)
                if (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino):
                    os.unlink(path.name, dir_fd=parent_fd)
            except OSError:
                pass
        raise
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(parent_fd)
