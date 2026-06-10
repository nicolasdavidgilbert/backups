from __future__ import annotations

from .archives import archive_for_backup_dir
from .config import ACTION_RESTORE
from .models import BackupError
from .operations import run_backup, run_restore


class OperationMixin:
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

