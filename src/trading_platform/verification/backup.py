from __future__ import annotations
import hashlib, json, shutil, tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

def _manifest(root: Path) -> dict[str,str]:
    out={}
    for p in sorted(x for x in root.rglob('*') if x.is_file()):
        out[str(p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
    return out

def backup_directory(source: str|Path, destination: str|Path) -> Path:
    source=Path(source); destination=Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest=_manifest(source)
    with tarfile.open(destination, 'w:gz') as tf:
        tf.add(source, arcname=source.name)
    manifest_path=destination.with_suffix(destination.suffix+'.manifest.json')
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2))
    return destination

def verify_backup_manifest(backup: str|Path, manifest_file: str|Path) -> bool:
    backup=Path(backup); manifest=json.loads(Path(manifest_file).read_text())
    with TemporaryDirectory() as td:
        with tarfile.open(backup, 'r:gz') as tf: tf.extractall(td, filter='data')
        root=next(Path(td).iterdir())
        return _manifest(root)==manifest

def restore_backup(backup: str|Path, destination: str|Path) -> Path:
    backup=Path(backup); destination=Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(backup, 'r:gz') as tf: tf.extractall(destination, filter='data')
    return destination
