from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import BACKUP_DIR_SUFFIX
from .models import BackupError


def latest_snapshot(base_path: Path) -> Path | None:
    snapshots = sorted(base_path.rglob("metadatos.snar"), key=lambda item: item.stat().st_mtime)
    return snapshots[-1] if snapshots else None


def latest_full_snapshot(root: Path) -> Path | None:
    full_root = root / "Iniciales"
    if not full_root.is_dir():
        return None
    snapshots = sorted(full_root.rglob("metadatos.snar"), key=lambda item: item.stat().st_mtime)
    return snapshots[-1] if snapshots else None


def resolve_backup_base(destination: str) -> Path:
    destination = destination.strip() or str(Path.home() / "Backups")
    destination_path = Path(destination).expanduser()
    if destination_path.is_absolute():
        return destination_path
    return Path.cwd() / destination_path


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def backup_timestamp(backup_dir: Path) -> float:
    manifest_path = backup_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            fecha = payload.get("fecha")
            if isinstance(fecha, str):
                return datetime.fromisoformat(fecha).timestamp()
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    snapshot = backup_dir / "metadatos.snar"
    if snapshot.is_file():
        return snapshot.stat().st_mtime
    return backup_dir.stat().st_mtime


def archive_for_backup_dir(backup_dir: Path) -> Path | None:
    if backup_dir.name.endswith("_FULL"):
        archive = backup_dir / "backup_FULL.tar.gz"
    elif backup_dir.name.endswith("_INC"):
        archive = backup_dir / "backup_INC.tar.gz"
    elif backup_dir.name.endswith("_DIFF"):
        archive = backup_dir / "backup_DIFF.tar.gz"
    else:
        return None
    return archive if archive.is_file() else None


def latest_backup_archive_for_source(source_text: str, destination_text: str) -> Path | None:
    source = Path(source_text).expanduser()
    source_name = source.name or "raiz"
    root = resolve_backup_base(destination_text) / f"{source_name}{BACKUP_DIR_SUFFIX}"
    if not root.is_dir():
        return None

    archives: list[tuple[float, Path]] = []
    for section in ("Iniciales", "Diferenciales", "Incrementales"):
        section_path = root / section
        if not section_path.is_dir():
            continue
        for backup_dir in section_path.iterdir():
            archive = archive_for_backup_dir(backup_dir)
            if archive is not None:
                archives.append((backup_timestamp(backup_dir), archive))
    if not archives:
        return None
    return max(archives, key=lambda item: item[0])[1]


def discover_restore_chain(backup_file: Path) -> list[Path]:
    backup_dir = backup_file.parent
    if backup_file.name == "backup_FULL.tar.gz" or backup_dir.name.endswith("_FULL"):
        return [backup_file]
    if not (backup_dir.name.endswith("_INC") or backup_dir.name.endswith("_DIFF")):
        return [backup_file]

    root = backup_dir.parent.parent
    full_root = root / "Iniciales"
    diff_root = root / "Diferenciales"
    inc_root = root / "Incrementales"
    selected_time = backup_timestamp(backup_dir)

    full_candidates = []
    if full_root.is_dir():
        for item in full_root.iterdir():
            archive = archive_for_backup_dir(item)
            if archive is not None:
                full_candidates.append((backup_timestamp(item), archive))

    previous_fulls = [(stamp, archive) for stamp, archive in full_candidates if stamp <= selected_time]
    if not previous_fulls:
        raise BackupError("No se encontró un backup completo previo para restaurar este backup.")
    full_time, full_archive = max(previous_fulls, key=lambda item: item[0])

    chain = [full_archive]
    base_time = full_time
    if diff_root.is_dir():
        diff_candidates = []
        for item in diff_root.iterdir():
            archive = archive_for_backup_dir(item)
            if archive is None:
                continue
            stamp = backup_timestamp(item)
            if full_time < stamp <= selected_time:
                diff_candidates.append((stamp, archive))
        if diff_candidates:
            base_time, diff_archive = max(diff_candidates, key=lambda item: item[0])
            chain.append(diff_archive)

    if backup_dir.name.endswith("_INC"):
        increments = []
        if inc_root.is_dir():
            for item in inc_root.iterdir():
                archive = archive_for_backup_dir(item)
                if archive is None:
                    continue
                stamp = backup_timestamp(item)
                if base_time < stamp <= selected_time:
                    increments.append((stamp, archive))
        chain.extend(archive for _, archive in sorted(increments, key=lambda item: item[0]))

    if chain[-1].resolve() != backup_file.resolve():
        raise BackupError("No se pudo reconstruir la cadena hasta el archivo seleccionado.")
    return chain
