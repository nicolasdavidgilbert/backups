#!/usr/bin/env python3
"""
Interfaz minimalista de terminal para backups completos e incrementales.

Ejecuta:
    python3 backup_tui.py
"""

from __future__ import annotations

import curses
import json
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


APP_TITLE = "Linux USB Backup"
BACKUP_DIR_SUFFIX = "_backups"
ESC_DELAY_MS = 10
ACTION_BACKUP = "Crear backup"
ACTION_RESTORE = "Restaurar backup"
FOCUS_COUNT = 6
BACKUP_MODES = ["Completa", "Incremental", "Diferencial"]
EXCLUDES = [
    ".cache",
    "node_modules",
    "__pycache__",
    ".Trash-*",
    "lost+found",
]


@dataclass(frozen=True)
class Device:
    name: str
    mountpoint: str
    size: str = ""
    label: str = ""
    model: str = ""
    is_ssd: bool | None = None

    @property
    def display_name(self) -> str:
        parts = [self.label or self.model or self.name]
        if self.size:
            parts.append(self.size)
        if self.is_ssd is True:
            parts.append("SSD")
        elif self.is_ssd is False:
            parts.append("externo")
        return " · ".join(parts)


class BackupError(Exception):
    pass


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def detect_external_devices() -> list[Device]:
    devices: list[Device] = []
    result = run(
        [
            "lsblk",
            "-J",
            "-o",
            "NAME,TYPE,TRAN,RM,ROTA,SIZE,LABEL,MODEL,FSTYPE,MOUNTPOINTS",
        ]
    )

    if result.returncode == 0 and result.stdout.strip():
        try:
            payload = json.loads(result.stdout)
            for disk in payload.get("blockdevices", []):
                devices.extend(device_entries_from_node(disk, disk))
        except json.JSONDecodeError:
            pass

    seen: set[str] = set()
    unique: list[Device] = []
    for device in devices:
        if device.mountpoint and device.mountpoint not in seen:
            seen.add(device.mountpoint)
            unique.append(device)

    if unique:
        return unique

    return detect_mount_fallbacks()


def device_entries_from_node(node: dict, root: dict) -> list[Device]:
    entries: list[Device] = []
    mountpoints = node.get("mountpoints") or []
    if isinstance(mountpoints, str):
        mountpoints = [mountpoints]

    for mountpoint in [item for item in mountpoints if item]:
        if looks_external(root, mountpoint):
            entries.append(
                Device(
                    name=f"/dev/{node.get('name', '')}",
                    mountpoint=mountpoint,
                    size=node.get("size") or root.get("size") or "",
                    label=node.get("label") or root.get("label") or "",
                    model=(root.get("model") or "").strip(),
                    is_ssd=is_ssd(root, node),
                )
            )

    for child in node.get("children") or []:
        entries.extend(device_entries_from_node(child, root))
    return entries


def looks_external(root: dict, mountpoint: str) -> bool:
    if mountpoint in {"/", "/boot", "/boot/efi"}:
        return False
    if str(root.get("tran") or "").lower() == "usb":
        return True
    if bool(root.get("rm")):
        return True
    external_prefixes = ("/media/", "/run/media/", "/mnt/")
    return mountpoint.startswith(external_prefixes)


def is_ssd(root: dict, node: dict) -> bool | None:
    rota = root.get("rota")
    if rota is None:
        rota = node.get("rota")
    if rota is None:
        return None
    return str(rota).strip().lower() in {"0", "false", "no"}


def detect_mount_fallbacks() -> list[Device]:
    candidates: list[Device] = []
    user = os.environ.get("USER", "")
    for base in [Path("/media") / user, Path("/run/media") / user, Path("/mnt")]:
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if child.is_dir() and os.access(child, os.W_OK):
                candidates.append(Device(name=child.name, mountpoint=str(child), label=child.name))
    return candidates


def ensure_tools() -> None:
    missing = [tool for tool in ("tar", "du", "lsblk") if shutil.which(tool) is None]
    if missing:
        raise BackupError("Faltan herramientas requeridas: " + ", ".join(missing))


def latest_snapshot(base_path: Path) -> Path | None:
    snapshots = sorted(base_path.rglob("metadatos.snar"), key=lambda item: item.stat().st_mtime)
    return snapshots[-1] if snapshots else None


def latest_full_snapshot(root: Path) -> Path | None:
    full_root = root / "Iniciales"
    if not full_root.is_dir():
        return None
    snapshots = sorted(full_root.rglob("metadatos.snar"), key=lambda item: item.stat().st_mtime)
    return snapshots[-1] if snapshots else None


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


def display_path(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    return "…" + value[-(width - 1):]


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


class BackupTUI:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.devices = detect_external_devices()
        self.selected_device = 0
        self.focus = 0
        self.action = ACTION_BACKUP
        self.source = self.devices[0].mountpoint if self.devices else str(Path.home())
        self.destination = str(Path.home() / "Backups")
        latest_backup = latest_backup_archive_for_source(self.source, self.destination)
        self.backup_file = str(latest_backup) if latest_backup else ""
        self.restore_destination = str(Path.home() / "Restaurado")
        self.mode = "Completa"
        self.status = ""
        self.log: list[str] = []
        self.cancel_requested = False
        self.device_offset = 0
        self.backup_finished = False
        self.status = self.focus_status()

    def run(self) -> None:
        curses.curs_set(0)
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_GREEN, -1)
        curses.init_pair(3, curses.COLOR_RED, -1)
        curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_CYAN)
        try:
            curses.set_escdelay(ESC_DELAY_MS)
        except AttributeError:
            pass
        curses.raw()
        self.stdscr.keypad(True)

        while True:
            self.draw()
            try:
                key = self.stdscr.getch()
            except KeyboardInterrupt:
                return
            if key == 3:
                return
            if key in (ord("q"), 27):
                if self.show_exit_menu():
                    return
                self.status = self.focus_status()
                continue
            if key == 9:
                self.move_focus(1)
            elif key == curses.KEY_BTAB:
                self.move_focus(-1)
            elif key in (curses.KEY_DOWN, curses.KEY_UP):
                if self.action == ACTION_BACKUP and self.focus == 0 and self.devices:
                    delta = 1 if key == curses.KEY_DOWN else -1
                    self.selected_device = (self.selected_device + delta) % len(self.devices)
                    self.keep_selected_device_visible()
                    self.status = f"USB seleccionado: {self.current_device().mountpoint}. Enter lo usa como origen."
                else:
                    delta = 1 if key == curses.KEY_DOWN else -1
                    self.move_focus(delta)
            elif key in (curses.KEY_LEFT, curses.KEY_RIGHT):
                if self.action == ACTION_BACKUP and self.focus == 0 and self.devices:
                    delta = -1 if key == curses.KEY_LEFT else 1
                    self.selected_device = (self.selected_device + delta) % len(self.devices)
                    self.keep_selected_device_visible()
                    self.status = f"Origen USB: {self.current_device().mountpoint}"
                elif self.focus == 1:
                    self.toggle_action()
                elif self.focus == 4 and self.action == ACTION_BACKUP:
                    self.toggle_mode()
            elif key in (10, 13):
                if self.focus == 0:
                    self.confirm_device_selection()
                elif self.focus == 1:
                    self.toggle_action()
                elif self.focus == 2:
                    if self.action == ACTION_RESTORE:
                        self.backup_file = self.prompt("Archivo .tar.gz a restaurar", self.backup_file)
                        self.status = self.focus_status()
                    else:
                        self.source = self.prompt("Directorio de origen", self.source)
                        self.update_latest_backup_file()
                        self.status = self.focus_status()
                elif self.focus == 3:
                    if self.action == ACTION_RESTORE:
                        self.restore_destination = self.prompt("Carpeta destino de restauración", self.restore_destination)
                        self.status = self.focus_status()
                    else:
                        self.destination = self.prompt("Directorio destino fuera del USB de origen", self.destination)
                        self.update_latest_backup_file()
                        self.status = self.focus_status()
                elif self.focus == 4:
                    if self.action == ACTION_BACKUP:
                        self.toggle_mode()
                elif self.focus == 5:
                    self.start_operation()

    def current_device(self) -> Device:
        return self.devices[self.selected_device]

    def focus_sequence(self) -> list[int]:
        if self.action == ACTION_RESTORE:
            return [1, 2, 3, 5]
        return list(range(FOCUS_COUNT))

    def move_focus(self, delta: int) -> None:
        sequence = self.focus_sequence()
        if self.focus not in sequence:
            self.focus = sequence[0]
        else:
            current = sequence.index(self.focus)
            self.focus = sequence[(current + delta) % len(sequence)]
        self.status = self.focus_status()

    def focus_status(self) -> str:
        if self.action == ACTION_RESTORE:
            messages = {
                1: "Enter cambia a crear backup.",
                2: "Enter edita el .tar.gz a restaurar. Se detecta la cadena automáticamente.",
                3: "Enter edita la carpeta segura donde extraer la restauración.",
                5: "Enter inicia la restauración. Esc abre el menú.",
            }
        else:
            messages = {
                0: "Flechas eligen USB. Enter lo usa como origen.",
                1: "Enter cambia a restaurar backup.",
                2: "Enter edita el origen a copiar.",
                3: "Enter edita el destino donde guardar backups.",
                4: "Enter o flechas cambian Completa/Incremental/Diferencial.",
                5: "Enter inicia el backup. Esc abre el menú.",
            }
        return messages.get(self.focus, "Tab cambia de campo. Esc abre el menú.")

    def update_latest_backup_file(self) -> None:
        latest_backup = latest_backup_archive_for_source(self.source, self.destination)
        self.backup_file = str(latest_backup) if latest_backup else ""

    def confirm_device_selection(self) -> None:
        if not self.devices:
            self.status = "No hay USB externo seleccionado; escribe el origen manualmente."
            self.focus = 2
            return
        self.source = self.current_device().mountpoint
        self.update_latest_backup_file()
        self.status = f"USB elegido como origen: {self.current_device().mountpoint}"
        self.focus = 3

    def toggle_action(self) -> None:
        self.action = ACTION_RESTORE if self.action == ACTION_BACKUP else ACTION_BACKUP
        if self.action == ACTION_RESTORE:
            self.update_latest_backup_file()
            if self.focus not in self.focus_sequence():
                self.focus = 1
        self.status = self.focus_status()

    def toggle_mode(self) -> None:
        current = BACKUP_MODES.index(self.mode) if self.mode in BACKUP_MODES else 0
        self.mode = BACKUP_MODES[(current + 1) % len(BACKUP_MODES)]
        self.status = f"Tipo de copia: {self.mode}"

    def keep_selected_device_visible(self) -> None:
        visible_count = 5
        if self.selected_device < self.device_offset:
            self.device_offset = self.selected_device
        elif self.selected_device >= self.device_offset + visible_count:
            self.device_offset = self.selected_device - visible_count + 1

    def draw(self, refresh: bool = True) -> None:
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        if height < 22 or width < 72:
            self.add(0, 0, "Amplía la terminal: mínimo recomendado 72x22.", curses.color_pair(3))
            if refresh:
                self.flush()
            return

        self.draw_box(0, 0, height, width, APP_TITLE)
        self.add(2, 3, "Copia de seguridad en terminal", curses.color_pair(1) | curses.A_BOLD)
        self.add(3, 3, "Selecciona el SSD de origen y define un destino fuera de ese disco.")

        left_w = width // 2 - 3
        right_x = left_w + 4
        if self.action == ACTION_RESTORE:
            self.draw_box(5, 2, 9, left_w, "Cadena de restauración")
            self.draw_restore_summary(7, 4, 5, left_w - 4)
        else:
            self.draw_box(5, 2, 9, left_w, "Discos externos")
            self.draw_devices(7, 4, left_w - 4)

        self.draw_box(5, right_x, 10, width - right_x - 2, "Configuración")
        self.field(7, right_x + 2, width - right_x - 6, 1, "Acción", self.action)
        if self.action == ACTION_RESTORE:
            self.field(9, right_x + 2, width - right_x - 6, 2, "Backup", self.backup_file or "Sin backup detectado")
            self.field(11, right_x + 2, width - right_x - 6, 3, "Restaurar en", self.restore_destination)
            self.field(13, right_x + 2, width - right_x - 6, -1, "Tipo", "Restauración")
        else:
            self.field(9, right_x + 2, width - right_x - 6, 2, "Origen", self.source)
            self.field(11, right_x + 2, width - right_x - 6, 3, "Destino", self.destination)
            self.field(13, right_x + 2, width - right_x - 6, 4, "Tipo", self.mode)

        button_text = "Restaurar" if self.action == ACTION_RESTORE else "Iniciar backup"
        self.draw_button(15, right_x + 2, button_text, self.focus == 5)
        self.draw_box(15, 2, height - 18, left_w, "Registro")
        self.draw_log(17, 4, height - 20, left_w - 4)

        status_style = curses.color_pair(2) if not self.status.lower().startswith("error") else curses.color_pair(3)
        self.add(height - 2, 3, self.status[: width - 6], status_style)
        hint = "Esc menú"
        self.add(height - 2, max(3, width - len(hint) - 3), hint, curses.color_pair(1) | curses.A_BOLD)
        if refresh:
            self.flush()

    def flush(self) -> None:
        self.stdscr.noutrefresh()
        curses.doupdate()


    def show_exit_menu(self) -> bool:
        selected = 1
        options = ["Salir", "Cancelar"]
        while True:
            self.draw(refresh=False)
            height, width = self.stdscr.getmaxyx()
            menu_w = min(62, max(42, width - 8))
            menu_h = 15
            y = max(1, (height - menu_h) // 2)
            x = max(1, (width - menu_w) // 2)
            for row in range(y, y + menu_h):
                self.add(row, x, " " * menu_w)
            self.draw_box(y, x, menu_h, menu_w, "Menú")
            self.add(y + 2, x + 3, "¿Qué quieres hacer?")
            for index, option in enumerate(options):
                style = curses.color_pair(4) | curses.A_BOLD if index == selected else curses.A_NORMAL
                self.add(y + 4, x + 4 + index * 12, f" {option} ", style)

            shortcuts = [
                "Tab / Shift+Tab: cambiar de campo",
                "Flechas: mover selección o cambiar acción/tipo",
                "Enter: confirmar, editar, iniciar o salir",
                "Esc / q: abrir este menú",
                "c: cerrar este menú",
                "c / Ctrl+C durante operación: cancelar",
            ]
            self.add(y + 6, x + 3, "Atajos", curses.color_pair(1) | curses.A_BOLD)
            for row, shortcut in enumerate(shortcuts, start=7):
                self.add(y + row, x + 3, shortcut[: menu_w - 6])
            self.add(y + menu_h - 2, x + 3, "Enter confirma · Esc cancela", curses.color_pair(1))
            self.flush()

            try:
                key = self.stdscr.getch()
            except KeyboardInterrupt:
                return False
            if key in (3, 27, ord("c"), ord("C")):
                return False
            if key in (curses.KEY_LEFT, curses.KEY_RIGHT, 9, curses.KEY_BTAB):
                selected = 1 - selected
            elif key in (10, 13):
                return selected == 0

    def draw_devices(self, y: int, x: int, width: int) -> None:
        if not self.devices:
            marker = ">" if self.focus == 0 else " "
            self.add(y, x, f"{marker} Ruta manual o directorio actual".ljust(width), curses.A_REVERSE if self.focus == 0 else 0)
            self.add(y + 2, x, "No se detectaron SSD externos montados."[:width])
            return

        visible = self.devices[self.device_offset : self.device_offset + 5]
        for row, device in enumerate(visible):
            index = self.device_offset + row
            selected = index == self.selected_device
            style = curses.A_REVERSE if selected and self.focus == 0 else 0
            marker = ">" if selected and self.focus == 0 else "*" if selected else " "
            detail = device.mountpoint if selected else device.display_name
            line = f"{marker} {detail}"
            self.add(y + row, x, line[:width].ljust(width), style)
        if len(self.devices) > 5:
            self.add(y + 5, x, f"{self.selected_device + 1}/{len(self.devices)}"[:width], curses.color_pair(1))


    def draw_restore_summary(self, y: int, x: int, height: int, width: int) -> None:
        if not self.backup_file:
            self.add(y, x, "No hay backup detectado para este origen."[:width])
            self.add(y + 1, x, "Edita el campo Backup manualmente."[:width], curses.color_pair(1))
            return

        backup_file = Path(self.backup_file).expanduser()
        self.add(y, x, display_path(str(backup_file), width))
        if not backup_file.is_file():
            self.add(y + 2, x, "El archivo no existe todavía."[:width], curses.color_pair(3))
            return
        try:
            chain = discover_restore_chain(backup_file)
        except BackupError as exc:
            self.add(y + 2, x, str(exc)[:width], curses.color_pair(3))
            return

        self.add(y + 1, x, f"Cadena: {len(chain)} archivo(s)"[:width], curses.color_pair(1))
        for row, archive in enumerate(chain[-max(1, height - 2):], start=2):
            self.add(y + row, x, display_path(archive.name, width))

    def field(self, y: int, x: int, width: int, focus: int, label: str, value: str) -> None:
        focused = self.focus == focus
        label_style = curses.color_pair(1) if focused else curses.A_NORMAL
        self.add(y, x, f"{label}: ", label_style | curses.A_BOLD)
        text_x = x + len(label) + 2
        text_width = max(10, width - len(label) - 2)
        style = curses.A_REVERSE if focused else curses.A_NORMAL
        visible_value = display_path(value, text_width)
        self.add(y, text_x, visible_value.ljust(text_width), style)

    def draw_button(self, y: int, x: int, text: str, focused: bool) -> None:
        style = curses.color_pair(4) | curses.A_BOLD if focused else curses.A_BOLD
        self.add(y, x, f"  {text}  ", style)

    def draw_log(self, y: int, x: int, height: int, width: int) -> None:
        for row, line in enumerate(self.log[-height:]):
            self.add(y + row, x, line[:width])

    def draw_box(self, y: int, x: int, height: int, width: int, title: str = "") -> None:
        for col in range(x + 1, x + width - 1):
            self.add(y, col, "─")
            self.add(y + height - 1, col, "─")
        for row in range(y + 1, y + height - 1):
            self.add(row, x, "│")
            self.add(row, x + width - 1, "│")
        self.add(y, x, "┌")
        self.add(y, x + width - 1, "┐")
        self.add(y + height - 1, x, "└")
        self.add(y + height - 1, x + width - 1, "┘")
        if title:
            self.add(y, x + 2, f" {title} ", curses.color_pair(1) | curses.A_BOLD)

    def add(self, y: int, x: int, text: str, style: int = 0) -> None:
        height, width = self.stdscr.getmaxyx()
        if not text or not (0 <= y < height and 0 <= x < width):
            return
        if y == height - 1 and x == width - 1:
            return
        max_chars = width - x
        if y == height - 1:
            max_chars = max(0, max_chars - 1)
        if max_chars <= 0:
            return
        try:
            self.stdscr.addnstr(y, x, text, max_chars, style)
        except curses.error:
            pass

    def prompt(self, title: str, current: str) -> str:
        curses.curs_set(1)
        height, width = self.stdscr.getmaxyx()
        value = current
        while True:
            self.draw(refresh=False)
            prompt = f"{title}: "
            self.add(height - 5, 3, "Enter guarda · Esc cancela · Ctrl+U limpia"[: width - 6], curses.color_pair(1))
            self.add(height - 4, 3, " " * (width - 6), curses.A_REVERSE)
            self.add(height - 4, 3, prompt + display_path(value, max(1, width - 6 - len(prompt))), curses.A_REVERSE)
            self.stdscr.move(height - 4, min(width - 5, 3 + len(prompt) + len(value)))
            self.flush()
            try:
                key = self.stdscr.getch()
            except KeyboardInterrupt:
                curses.curs_set(0)
                return current
            if key == 3:
                curses.curs_set(0)
                return current
            if key in (10, 13):
                curses.curs_set(0)
                return value.strip() or current
            if key == 27:
                curses.curs_set(0)
                return current
            if key in (curses.KEY_BACKSPACE, 127, 8):
                value = value[:-1]
            elif key == 21:
                value = ""
            elif 32 <= key <= 126:
                value += chr(key)

    def start_operation(self) -> None:
        if self.action == ACTION_RESTORE:
            self.start_restore()
        else:
            self.start_backup()

    def start_backup(self) -> None:
        self.log = []
        self.cancel_requested = False
        self.backup_finished = False
        device = None
        self.status = "Ejecutando backup · pulsa c para cancelar"
        self.stdscr.nodelay(True)

        def should_cancel() -> bool:
            key = self.stdscr.getch()
            if key in (3, ord("c"), ord("C")):
                self.cancel_requested = True
            return self.cancel_requested

        def on_message(message: str, transient: bool = False) -> None:
            if transient:
                self.status = message + " · pulsa c para cancelar"
            else:
                self.log.append(message)
            self.draw()

        try:
            backup_dir = run_backup(self.source, device, self.destination, self.mode, on_message, should_cancel)
        except BackupError as exc:
            self.status = f"Error: {exc}"
            self.log.append(str(exc))
        except KeyboardInterrupt:
            self.status = "Cancelado."
        else:
            archive = archive_for_backup_dir(backup_dir)
            if archive is not None:
                self.backup_file = str(archive)
            log_path = backup_dir / "backup.log"
            self.log.append(f"Log guardado en: {log_path}")
            log_path.write_text("\n".join(self.log), encoding="utf-8")
            self.backup_finished = True
            self.focus = 1
            self.status = f"Listo: {backup_dir}. Esc o q abren el menú. Ctrl+C sale directo."
        finally:
            self.stdscr.nodelay(False)

    def start_restore(self) -> None:
        self.log = []
        self.cancel_requested = False
        self.backup_finished = False
        self.status = "Restaurando · pulsa c para cancelar"
        self.stdscr.nodelay(True)

        def should_cancel() -> bool:
            key = self.stdscr.getch()
            if key in (3, ord("c"), ord("C")):
                self.cancel_requested = True
            return self.cancel_requested

        def on_message(message: str, transient: bool = False) -> None:
            if transient:
                self.status = message + " · pulsa c para cancelar"
            else:
                self.log.append(message)
            self.draw()

        try:
            restore_dir = run_restore(self.backup_file, self.restore_destination, on_message, should_cancel)
        except BackupError as exc:
            self.status = f"Error: {exc}"
            self.log.append(str(exc))
        except KeyboardInterrupt:
            self.status = "Cancelado."
        else:
            log_path = restore_dir / "restore.log"
            self.log.append(f"Log guardado en: {log_path}")
            log_path.write_text("\n".join(self.log), encoding="utf-8")
            self.backup_finished = True
            self.focus = 1
            self.status = f"Listo: {restore_dir}. Esc o q abren el menú. Ctrl+C sale directo."
        finally:
            self.stdscr.nodelay(False)


def main() -> int:
    try:
        os.environ.setdefault("ESCDELAY", str(ESC_DELAY_MS))
        curses.wrapper(lambda stdscr: BackupTUI(stdscr).run())
    except KeyboardInterrupt:
        return 130
    except BackupError as exc:
        print(f"Error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
