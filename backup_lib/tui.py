from __future__ import annotations

import curses
from pathlib import Path

from .archives import latest_backup_archive_for_source
from .config import (
    ACTION_BACKUP,
    ACTION_RESTORE,
    BACKUP_MODES,
    ESC_DELAY_MS,
    FOCUS_COUNT,
)
from .devices import detect_external_devices
from .dialogs import DialogMixin
from .models import Device
from .render import RenderMixin
from .workflows import OperationMixin


class BackupTUI(DialogMixin, OperationMixin, RenderMixin):
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

