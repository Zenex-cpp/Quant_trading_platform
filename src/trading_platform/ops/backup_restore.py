from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import tarfile
import time
from typing import Callable, Iterable


class BackupRestoreError(RuntimeError):
    pass


_SECRET_PARTS = {
    "secret",
    "secrets",
    "credential",
    "credentials",
    ".env",
    "password",
    "token",
    "private_key",
    "api_key",
    "api_secret",
}


def _is_secret_like(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    if any(part in _SECRET_PARTS for part in parts):
        return True
    name = path.name.lower()
    return any(marker in name for marker in ("secret", "credential", "password", "token", "private_key", "api_key", "api_secret"))


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _safe_rel(path: Path, root: Path) -> str:
    rel = path.resolve().relative_to(root.resolve())
    posix = PurePosixPath(rel.as_posix())
    if posix.is_absolute() or ".." in posix.parts:
        raise BackupRestoreError("BACKUP_PATH_TRAVERSAL")
    return posix.as_posix()


@dataclass(frozen=True)
class BackupPolicy:
    source_root: Path
    include_prefixes: tuple[str, ...]
    destination: Path
    rpo_seconds: int
    rto_seconds: int


@dataclass(frozen=True)
class BackupRecord:
    backup_id: str
    created_at_ns: int
    source_root: str
    archive_path: str
    manifest_hash: str
    file_count: int
    rpo_seconds: int
    rto_seconds: int
    rpo_age_seconds: float
    evidence_class: str = "INTERNAL_TEST_EVIDENCE"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class BackupRestoreService:
    """Deterministic local backup/restore drill for governed test artifacts.

    This service deliberately does not claim infrastructure or production durability.
    It proves only that an allowlisted filesystem snapshot can be materialized,
    integrity-checked, restored into a clean destination, and replay-verified.
    """

    MANIFEST_NAME = "backup_manifest.json"

    def __init__(self, *, now_ns: Callable[[], int] | None = None) -> None:
        self._now_ns = now_ns or time.time_ns

    def create_backup(
        self,
        *,
        policy: BackupPolicy,
        latest_event_time_ns: int,
        backup_id: str,
    ) -> BackupRecord:
        if not backup_id or "/" in backup_id or "\\" in backup_id:
            raise BackupRestoreError("BACKUP_ID_INVALID")
        root = policy.source_root.resolve()
        destination = policy.destination.resolve()
        if not root.exists() or not root.is_dir():
            raise BackupRestoreError("BACKUP_SOURCE_ROOT_INVALID")
        destination.parent.mkdir(parents=True, exist_ok=True)
        created_at_ns = self._now_ns()
        if latest_event_time_ns > created_at_ns:
            raise BackupRestoreError("BACKUP_CAPTURE_BEFORE_LATEST_EVENT")
        rpo_age_seconds = (created_at_ns - latest_event_time_ns) / 1_000_000_000
        if rpo_age_seconds > policy.rpo_seconds:
            raise BackupRestoreError("RPO_TARGET_BREACHED")

        files: list[tuple[str, bytes]] = []
        prefixes = tuple(PurePosixPath(p).as_posix().rstrip("/") for p in policy.include_prefixes)
        for prefix in prefixes:
            candidate = (root / prefix).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise BackupRestoreError("BACKUP_INCLUDE_PATH_OUTSIDE_ROOT") from exc
            if not candidate.exists():
                raise BackupRestoreError(f"BACKUP_INCLUDE_PATH_MISSING:{prefix}")
            paths = [candidate] if candidate.is_file() else sorted(candidate.rglob("*"))
            for path in paths:
                if not path.is_file():
                    continue
                rel = _safe_rel(path, root)
                if _is_secret_like(Path(rel)):
                    raise BackupRestoreError(f"BACKUP_SECRET_LIKE_PATH_FORBIDDEN:{rel}")
                data = path.read_bytes()
                files.append((rel, data))

        if not files:
            raise BackupRestoreError("BACKUP_EMPTY")
        files.sort(key=lambda item: item[0])
        manifest_entries = [
            {"path": rel, "size": len(data), "sha256": _sha256_bytes(data)}
            for rel, data in files
        ]
        manifest = {
            "schema_version": "1",
            "backup_id": backup_id,
            "created_at_ns": created_at_ns,
            "source_root": root.as_posix(),
            "rpo_seconds": policy.rpo_seconds,
            "rto_seconds": policy.rto_seconds,
            "evidence_class": "INTERNAL_TEST_EVIDENCE",
            "files": manifest_entries,
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        manifest_hash = _sha256_bytes(manifest_bytes)

        with tarfile.open(destination, mode="w:gz") as tar:
            info = tarfile.TarInfo(self.MANIFEST_NAME)
            info.size = len(manifest_bytes)
            info.mode = 0o644
            info.mtime = 0
            import io

            tar.addfile(info, io.BytesIO(manifest_bytes))
            for rel, data in files:
                info = tarfile.TarInfo(rel)
                info.size = len(data)
                info.mode = 0o644
                info.mtime = 0
                tar.addfile(info, io.BytesIO(data))

        return BackupRecord(
            backup_id=backup_id,
            created_at_ns=created_at_ns,
            source_root=root.as_posix(),
            archive_path=destination.as_posix(),
            manifest_hash=manifest_hash,
            file_count=len(files),
            rpo_seconds=policy.rpo_seconds,
            rto_seconds=policy.rto_seconds,
            rpo_age_seconds=rpo_age_seconds,
        )

    def restore(
        self,
        *,
        archive_path: Path,
        destination_root: Path,
    ) -> tuple[BackupRecord, float]:
        start_ns = self._now_ns()
        archive = archive_path.resolve()
        destination = destination_root.resolve()
        if not archive.is_file():
            raise BackupRestoreError("RESTORE_ARCHIVE_MISSING")
        if destination.exists() and any(destination.iterdir()):
            raise BackupRestoreError("RESTORE_DESTINATION_NOT_EMPTY")
        destination.mkdir(parents=True, exist_ok=True)

        with tarfile.open(archive, mode="r:gz") as tar:
            members = tar.getmembers()
            member_names = [m.name for m in members]
            if self.MANIFEST_NAME not in member_names:
                raise BackupRestoreError("RESTORE_MANIFEST_MISSING")
            manifest_member = tar.getmember(self.MANIFEST_NAME)
            raw_manifest = tar.extractfile(manifest_member)
            if raw_manifest is None:
                raise BackupRestoreError("RESTORE_MANIFEST_UNREADABLE")
            manifest_bytes = raw_manifest.read()
            manifest = json.loads(manifest_bytes.decode())
            if manifest.get("evidence_class") != "INTERNAL_TEST_EVIDENCE":
                raise BackupRestoreError("RESTORE_EVIDENCE_CLASS_INVALID")
            manifest_hash = _sha256_bytes(manifest_bytes)
            expected_files = {str(x["path"]): x for x in manifest.get("files", [])}
            for member in members:
                if member.name == self.MANIFEST_NAME:
                    continue
                p = PurePosixPath(member.name)
                if p.is_absolute() or ".." in p.parts or member.issym() or member.islnk():
                    raise BackupRestoreError("RESTORE_UNSAFE_ARCHIVE_MEMBER")
                if member.name not in expected_files:
                    raise BackupRestoreError("RESTORE_UNDECLARED_MEMBER")
                if _is_secret_like(Path(member.name)):
                    raise BackupRestoreError("RESTORE_SECRET_LIKE_PATH_FORBIDDEN")
                target = (destination / member.name).resolve()
                try:
                    target.relative_to(destination)
                except ValueError as exc:
                    raise BackupRestoreError("RESTORE_PATH_TRAVERSAL") from exc
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise BackupRestoreError("RESTORE_MEMBER_UNREADABLE")
                target.write_bytes(extracted.read())

        for rel, expected in expected_files.items():
            target = destination / rel
            if not target.is_file():
                raise BackupRestoreError(f"RESTORE_FILE_MISSING:{rel}")
            data = target.read_bytes()
            if len(data) != int(expected["size"]):
                raise BackupRestoreError(f"RESTORE_SIZE_MISMATCH:{rel}")
            if _sha256_bytes(data) != str(expected["sha256"]):
                raise BackupRestoreError(f"RESTORE_HASH_MISMATCH:{rel}")

        end_ns = self._now_ns()
        elapsed_seconds = max(0.0, (end_ns - start_ns) / 1_000_000_000)
        record = BackupRecord(
            backup_id=str(manifest["backup_id"]),
            created_at_ns=int(manifest["created_at_ns"]),
            source_root=str(manifest["source_root"]),
            archive_path=archive.as_posix(),
            manifest_hash=manifest_hash,
            file_count=len(expected_files),
            rpo_seconds=int(manifest["rpo_seconds"]),
            rto_seconds=int(manifest["rto_seconds"]),
            rpo_age_seconds=0.0,
        )
        if elapsed_seconds > record.rto_seconds:
            raise BackupRestoreError("RTO_TARGET_BREACHED")
        return record, elapsed_seconds
