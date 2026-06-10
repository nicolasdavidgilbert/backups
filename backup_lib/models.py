from __future__ import annotations

from dataclasses import dataclass


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
