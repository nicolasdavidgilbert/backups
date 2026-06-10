from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .archives import (
    discover_restore_chain,
    is_relative_to,
    latest_full_snapshot,
    latest_snapshot,
    resolve_backup_base,
)
from .commands import (
    ensure_destination_space,
    ensure_safe_restore_destination,
    ensure_tools,
    human_size,
    run,
)
from .config import BACKUP_DIR_SUFFIX, EXCLUDES
from .models import BackupError, Device


def run_backup(source_text: str, device: Device | None, destination_text: str, mode: str, on_message, should_cancel) -> Path:
    ensure_tools()

    source = Path(source_text).expanduser()
    if not source.is_dir():
        raise BackupError(f"El origen no existe o no es un directorio: {source}")
    if not os.access(source, os.R_OK):
        raise BackupError(f"Sin permisos de lectura en origen: {source}")

    backup_base = resolve_backup_base(destination_text)
    source_real = source.resolve()
    backup_base_real = backup_base.resolve(strict=False)
    if backup_base_real == source_real or is_relative_to(backup_base_real, source_real):
        raise BackupError("El destino no puede estar dentro del directorio de origen.")
    ensure_destination_space(backup_base, source)

    dir_name = source.name or "raiz"
    now = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
    root = backup_base / f"{dir_name}{BACKUP_DIR_SUFFIX}"

    previous_snapshot = None
    if mode == "Completa":
        backup_dir = root / "Iniciales" / f"{now}_FULL"
        filename = backup_dir / "backup_FULL.tar.gz"
        snapshot = backup_dir / "metadatos.snar"
    elif mode == "Incremental":
        if not root.is_dir():
            raise BackupError(f"No hay backups previos para '{dir_name}' en {backup_base}")
        previous_snapshot = latest_snapshot(root)
        if previous_snapshot is None:
            raise BackupError("No se encontró un archivo metadatos.snar previo.")
        backup_dir = root / "Incrementales" / f"{now}_INC"
        filename = backup_dir / "backup_INC.tar.gz"
        snapshot = backup_dir / "metadatos.snar"
    elif mode == "Diferencial":
        if not root.is_dir():
            raise BackupError(f"No hay backup completo previo para '{dir_name}' en {backup_base}")
        previous_snapshot = latest_full_snapshot(root)
        if previous_snapshot is None:
            raise BackupError("No se encontró un backup completo base para el diferencial.")
        backup_dir = root / "Diferenciales" / f"{now}_DIFF"
        filename = backup_dir / "backup_DIFF.tar.gz"
        snapshot = backup_dir / "metadatos.snar"
    else:
        raise BackupError(f"Tipo de copia no soportado: {mode}")

    try:
        backup_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise BackupError(f"No se pudo crear el destino: {exc}") from exc

    if not os.access(backup_dir, os.W_OK):
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise BackupError(f"No se puede escribir en el destino: {backup_dir}")

    if mode in {"Incremental", "Diferencial"}:
        shutil.copy2(previous_snapshot, snapshot)

    source_human_size = human_size(source)
    on_message(f"Origen: {source}")
    on_message(f"Destino: {backup_dir}")
    on_message(f"Tamaño a procesar: {source_human_size}")
    if EXCLUDES:
        on_message("Exclusiones: " + ", ".join(EXCLUDES))
    on_message("Comprimiendo con tar...")

    command = [
        "tar",
        "-czPf",
        str(filename),
        f"--listed-incremental={snapshot}",
        "--no-check-device",
    ]
    for item in EXCLUDES:
        command.extend(["--exclude", item])
    command.append(str(source))

    error_log = backup_dir / "tar_error.log"
    process = None
    try:
        with error_log.open("w", encoding="utf-8") as stderr_file:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=stderr_file, text=True)
            spinner = "|/-\\"
            tick = 0
            while process.poll() is None:
                if should_cancel():
                    raise KeyboardInterrupt
                on_message(f"Procesando {spinner[tick % len(spinner)]}", transient=True)
                tick += 1
                time.sleep(0.15)
    except KeyboardInterrupt as exc:
        if process and process.poll() is None:
            process.send_signal(signal.SIGTERM)
            time.sleep(0.5)
            if process.poll() is None:
                process.kill()
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise BackupError("Proceso cancelado. Se eliminó la copia parcial.") from exc

    if process.returncode != 0:
        detail = error_log.read_text(encoding="utf-8", errors="replace").strip()
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise BackupError(detail or "tar terminó con error.")
    error_log.unlink(missing_ok=True)

    on_message("Verificando integridad del archivo tar.gz...")
    test_result = run(["tar", "-tzf", str(filename)])
    if test_result.returncode != 0:
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise BackupError("El backup se creó, pero falló la verificación de integridad.")

    backup_human_size = human_size(filename)
    manifest = {
        "fecha": datetime.now().isoformat(),
        "tipo": mode,
        "origen": str(source),
        "destino": str(backup_dir),
        "archivo": str(filename),
        "tamano_origen": source_human_size,
        "tamano_backup": backup_human_size,
        "exclusiones": EXCLUDES,
    }
    (backup_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    on_message(f"Copia {mode.lower()} completada. Archivo: {filename}")
    on_message(f"Tamaño final: {backup_human_size}")
    return backup_dir



def run_restore(backup_text: str, destination_text: str, on_message, should_cancel) -> Path:
    ensure_tools()

    if not backup_text.strip():
        raise BackupError("El campo Backup está vacío. Escribe o selecciona un .tar.gz.")

    backup_file = Path(backup_text).expanduser()
    if not backup_file.is_file():
        raise BackupError(f"El archivo de backup no existe: {backup_file}")
    if backup_file.suffixes[-2:] != [".tar", ".gz"]:
        raise BackupError("El archivo de backup debe ser .tar.gz")

    restore_dir = Path(destination_text.strip() or str(Path.home() / "Restaurado")).expanduser()
    ensure_safe_restore_destination(restore_dir)
    restore_dir.mkdir(parents=True, exist_ok=True)
    if not os.access(restore_dir, os.W_OK):
        raise BackupError(f"No se puede escribir en el destino: {restore_dir}")

    chain = discover_restore_chain(backup_file)
    on_message(f"Backup seleccionado: {backup_file}")
    on_message(f"Restaurar en: {restore_dir}")
    on_message(f"Cadena detectada: {len(chain)} archivo(s)")
    for archive in chain:
        on_message(f"- {archive}")

    on_message("Verificando integridad de la cadena...")
    for archive in chain:
        test_result = run(["tar", "-tzf", str(archive)])
        if test_result.returncode != 0:
            raise BackupError(f"Falló la verificación de integridad: {archive}")

    error_log = restore_dir / "restore_error.log"
    try:
        with error_log.open("w", encoding="utf-8") as stderr_file:
            for index, archive in enumerate(chain, start=1):
                on_message(f"Extrayendo {index}/{len(chain)}: {archive.name}")
                command = [
                    "tar",
                    "--listed-incremental=/dev/null",
                    "-xzf",
                    str(archive),
                    "-C",
                    str(restore_dir),
                ]
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=stderr_file, text=True)
                spinner = "|/-\\"
                tick = 0
                while process.poll() is None:
                    if should_cancel():
                        raise KeyboardInterrupt
                    on_message(f"Restaurando {index}/{len(chain)} {spinner[tick % len(spinner)]}", transient=True)
                    tick += 1
                    time.sleep(0.15)
                if process.returncode != 0:
                    detail = error_log.read_text(encoding="utf-8", errors="replace").strip()
                    raise BackupError(detail or f"tar terminó con error al restaurar: {archive}")
    except KeyboardInterrupt as exc:
        raise BackupError("Restauración cancelada. Revisa la carpeta destino por si quedaron archivos parciales.") from exc
    error_log.unlink(missing_ok=True)

    on_message(f"Restauración completada en: {restore_dir}")
    return restore_dir
