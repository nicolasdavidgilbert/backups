from __future__ import annotations

import curses
from pathlib import Path

from .archives import discover_restore_chain
from .config import ACTION_RESTORE, APP_TITLE
from .models import BackupError
from .ui_utils import display_path


class RenderMixin:
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

