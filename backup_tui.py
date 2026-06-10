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


def human_size(path: Path) -> str:
    result = run(["du", "-sh", str(path)])
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.split("\t", 1)[0].strip()
    return "desconocido"


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

    dir_name = source.name or "raiz"
    now = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
    root = backup_base / f"{dir_name}{BACKUP_DIR_SUFFIX}"

    if mode == "Completa":
        backup_dir = root / "Iniciales" / f"{now}_FULL"
        filename = backup_dir / "backup_FULL.tar.gz"
        snapshot = backup_dir / "metadatos.snar"
    else:
        if not root.is_dir():
            raise BackupError(f"No hay backups previos para '{dir_name}' en {backup_base}")
        previous_snapshot = latest_snapshot(root)
        if previous_snapshot is None:
            raise BackupError("No se encontró un archivo metadatos.snar previo.")
        backup_dir = root / "Incrementales" / f"{now}_INC"
        filename = backup_dir / "backup_INC.tar.gz"
        snapshot = backup_dir / "metadatos.snar"

    try:
        backup_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise BackupError(f"No se pudo crear el destino: {exc}") from exc

    if not os.access(backup_dir, os.W_OK):
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise BackupError(f"No se puede escribir en el destino: {backup_dir}")

    if mode == "Incremental":
        shutil.copy2(previous_snapshot, snapshot)

    on_message(f"Origen: {source}")
    on_message(f"Destino: {backup_dir}")
    on_message(f"Tamaño a procesar: {human_size(source)}")
    on_message("Comprimiendo con tar...")

    command = [
        "tar",
        "-czPf",
        str(filename),
        f"--listed-incremental={snapshot}",
        "--no-check-device",
        str(source),
    ]

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

    on_message(f"Copia {mode.lower()} completada. Archivo: {filename}")
    on_message(f"Tamaño final: {human_size(filename)}")
    return backup_dir


class BackupTUI:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.devices = detect_external_devices()
        self.selected_device = 0
        self.focus = 0
        self.source = self.devices[0].mountpoint if self.devices else str(Path.home())
        self.destination = str(Path.home() / "Backups")
        self.mode = "Completa"
        self.status = "Tab cambia de campo · Enter confirma/edita/inicia · q sale"
        self.log: list[str] = []
        self.cancel_requested = False
        self.device_offset = 0
        self.backup_finished = False

    def run(self) -> None:
        curses.curs_set(0)
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_GREEN, -1)
        curses.init_pair(3, curses.COLOR_RED, -1)
        curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_CYAN)
        self.stdscr.keypad(True)

        while True:
            self.draw()
            try:
                key = self.stdscr.getch()
            except KeyboardInterrupt:
                return
            if key == ord("q"):
                return
            if key == 27:
                if self.show_exit_menu():
                    return
                continue
            if key == 9:
                self.focus = (self.focus + 1) % 5
            elif key in (curses.KEY_DOWN, curses.KEY_UP):
                if self.focus == 0 and self.devices:
                    delta = 1 if key == curses.KEY_DOWN else -1
                    self.selected_device = (self.selected_device + delta) % len(self.devices)
                    self.keep_selected_device_visible()
                    self.status = f"Origen USB: {self.current_device().mountpoint}"
                else:
                    delta = 1 if key == curses.KEY_DOWN else -1
                    self.focus = (self.focus + delta) % 5
            elif key in (curses.KEY_LEFT, curses.KEY_RIGHT):
                if self.focus == 0 and self.devices:
                    delta = -1 if key == curses.KEY_LEFT else 1
                    self.selected_device = (self.selected_device + delta) % len(self.devices)
                    self.keep_selected_device_visible()
                    self.status = f"Origen USB: {self.current_device().mountpoint}"
                elif self.focus == 3:
                    self.toggle_mode()
            elif key in (10, 13):
                if self.focus == 0:
                    self.confirm_device_selection()
                elif self.focus == 1:
                    self.source = self.prompt("Directorio de origen", self.source)
                elif self.focus == 2:
                    self.destination = self.prompt("Directorio destino fuera del USB de origen", self.destination)
                elif self.focus == 3:
                    self.toggle_mode()
                elif self.focus == 4:
                    if self.backup_finished:
                        return
                    self.start_backup()

    def current_device(self) -> Device:
        return self.devices[self.selected_device]

    def confirm_device_selection(self) -> None:
        if not self.devices:
            self.status = "No hay USB externo seleccionado; escribe el origen manualmente."
            self.focus = 1
            return
        self.source = self.current_device().mountpoint
        self.status = f"USB elegido como origen: {self.current_device().mountpoint}"
        self.focus = 2

    def toggle_mode(self) -> None:
        self.mode = "Incremental" if self.mode == "Completa" else "Completa"
        self.status = f"Tipo de copia: {self.mode}"

    def keep_selected_device_visible(self) -> None:
        visible_count = 5
        if self.selected_device < self.device_offset:
            self.device_offset = self.selected_device
        elif self.selected_device >= self.device_offset + visible_count:
            self.device_offset = self.selected_device - visible_count + 1

    def draw(self) -> None:
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        if height < 22 or width < 72:
            self.add(0, 0, "Amplía la terminal: mínimo recomendado 72x22.", curses.color_pair(3))
            self.stdscr.refresh()
            return

        self.draw_box(0, 0, height, width, APP_TITLE)
        self.add(2, 3, "Copia de seguridad en terminal", curses.color_pair(1) | curses.A_BOLD)
        self.add(3, 3, "Selecciona el SSD de origen y define un destino fuera de ese disco.")

        left_w = width // 2 - 3
        right_x = left_w + 4
        self.draw_box(5, 2, 9, left_w, "Discos externos")
        self.draw_devices(7, 4, left_w - 4)

        self.draw_box(5, right_x, 9, width - right_x - 2, "Configuración")
        self.field(7, right_x + 2, width - right_x - 6, 1, "Origen", self.source)
        self.field(9, right_x + 2, width - right_x - 6, 2, "Destino", self.destination)
        self.field(11, right_x + 2, width - right_x - 6, 3, "Tipo", self.mode)

        button_text = "Salir" if self.backup_finished else "Iniciar backup"
        self.draw_button(15, right_x + 2, button_text, self.focus == 4)
        self.draw_box(15, 2, height - 18, left_w, "Registro")
        self.draw_log(17, 4, height - 20, left_w - 4)

        status_style = curses.color_pair(2) if not self.status.lower().startswith("error") else curses.color_pair(3)
        self.add(height - 2, 3, self.status[: width - 6], status_style)
        hint = "Esc menú"
        self.add(height - 2, max(3, width - len(hint) - 3), hint, curses.color_pair(1) | curses.A_BOLD)
        self.stdscr.refresh()


    def show_exit_menu(self) -> bool:
        selected = 0
        options = ["Salir", "Cancelar"]
        while True:
            self.draw()
            height, width = self.stdscr.getmaxyx()
            menu_w = min(34, max(24, width - 8))
            menu_h = 7
            y = max(1, (height - menu_h) // 2)
            x = max(1, (width - menu_w) // 2)
            self.draw_box(y, x, menu_h, menu_w, "Menú")
            self.add(y + 2, x + 3, "¿Qué quieres hacer?")
            for index, option in enumerate(options):
                style = curses.color_pair(4) | curses.A_BOLD if index == selected else curses.A_NORMAL
                self.add(y + 4, x + 4 + index * 12, f" {option} ", style)
            self.add(y + menu_h - 2, x + 3, "Enter confirma · Esc cancela", curses.color_pair(1))
            self.stdscr.refresh()

            try:
                key = self.stdscr.getch()
            except KeyboardInterrupt:
                return True
            if key in (27, ord("c"), ord("C")):
                return False
            if key in (curses.KEY_LEFT, curses.KEY_RIGHT, 9):
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

    def field(self, y: int, x: int, width: int, focus: int, label: str, value: str) -> None:
        focused = self.focus == focus
        label_style = curses.color_pair(1) if focused else curses.A_NORMAL
        self.add(y, x, f"{label}: ", label_style | curses.A_BOLD)
        text_x = x + len(label) + 2
        text_width = max(10, width - len(label) - 2)
        style = curses.A_REVERSE if focused else curses.A_NORMAL
        self.add(y, text_x, value[:text_width].ljust(text_width), style)

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
            self.draw()
            prompt = f"{title}: "
            self.add(height - 4, 3, " " * (width - 6), curses.A_REVERSE)
            self.add(height - 4, 3, prompt + value, curses.A_REVERSE)
            self.stdscr.move(height - 4, min(width - 5, 3 + len(prompt) + len(value)))
            try:
                key = self.stdscr.getch()
            except KeyboardInterrupt:
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

    def start_backup(self) -> None:
        self.log = []
        self.cancel_requested = False
        self.backup_finished = False
        device = None
        self.status = "Ejecutando backup · pulsa c para cancelar"
        self.stdscr.nodelay(True)

        def should_cancel() -> bool:
            key = self.stdscr.getch()
            if key in (ord("c"), ord("C")):
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
            self.backup_finished = True
            self.focus = 4
            self.status = f"Listo: {backup_dir}. Pulsa Enter para salir."
        finally:
            self.stdscr.nodelay(False)


def main() -> int:
    try:
        curses.wrapper(lambda stdscr: BackupTUI(stdscr).run())
    except KeyboardInterrupt:
        return 130
    except BackupError as exc:
        print(f"Error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
