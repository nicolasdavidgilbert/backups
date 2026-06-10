from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .models import BackupError


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def ensure_tools() -> None:
    missing = [tool for tool in ("tar", "du", "lsblk") if shutil.which(tool) is None]
    if missing:
        raise BackupError("Faltan herramientas requeridas: " + ", ".join(missing))


def human_size(path: Path) -> str:
    result = run(["du", "-sh", str(path)])
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.split("\t", 1)[0].strip()
    return "desconocido"


def disk_size_bytes(path: Path) -> int:
    result = run(["du", "-sb", str(path)])
    if result.returncode != 0 or not result.stdout.strip():
        raise BackupError(f"No se pudo calcular el tamaño de: {path}")
    try:
        return int(result.stdout.split()[0])
    except (IndexError, ValueError) as exc:
        raise BackupError(f"Tamaño de origen no válido: {path}") from exc


def ensure_destination_space(backup_base: Path, source: Path) -> None:
    backup_base.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(backup_base)
    source_size = disk_size_bytes(source)
    if usage.free < source_size * 0.3:
        raise BackupError("Puede no haber espacio suficiente en el destino.")


def ensure_safe_restore_destination(destination: Path) -> None:
    blocked = {
        Path("/"),
        Path.home(),
        Path("/bin"),
        Path("/boot"),
        Path("/dev"),
        Path("/etc"),
        Path("/home"),
        Path("/lib"),
        Path("/lib64"),
        Path("/opt"),
        Path("/proc"),
        Path("/root"),
        Path("/run"),
        Path("/sbin"),
        Path("/sys"),
        Path("/tmp"),
        Path("/usr"),
        Path("/var"),
    }
    resolved = destination.expanduser().resolve(strict=False)
    if resolved in blocked:
        raise BackupError("El destino de restauración debe ser una carpeta específica, no una ruta del sistema.")
