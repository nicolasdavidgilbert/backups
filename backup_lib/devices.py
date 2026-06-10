from __future__ import annotations

import json
import os
from pathlib import Path

from .commands import run
from .models import Device


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
