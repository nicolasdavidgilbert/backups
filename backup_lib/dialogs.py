from __future__ import annotations

import curses

from .ui_utils import display_path


class DialogMixin:
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

