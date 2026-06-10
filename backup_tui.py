#!/usr/bin/env python3
"""Terminal entry point for Linux USB Backup."""

from __future__ import annotations

import curses
import os

from backup_lib.config import ESC_DELAY_MS
from backup_lib.models import BackupError
from backup_lib.tui import BackupTUI


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
