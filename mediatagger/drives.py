"""The drives table: which physical disk each file lives on, and which of them are plugged in right now.

Lives in the same SQLite file as the file index (data/index.db). A drive is identified by its volume serial
number, never by its letter: the letter changes every time a disk is plugged into another port.
"""
from __future__ import annotations

import csv
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, fields
from datetime import date, datetime
from pathlib import Path

DRIVE_COLUMNS = {
    "name": "TEXT PRIMARY KEY",  # "Splash IV": also the first part of every file key
    "label": "TEXT DEFAULT ''",  # what is written on the disk ("Branco Estrela")
    "serial": "TEXT DEFAULT ''",  # volume serial, filled in the first time the disk is plugged in
    "location": "TEXT DEFAULT ''",
    "status": "TEXT DEFAULT ''",
    "size_gb": "REAL",
    "used_gb": "REAL",
    "free_gb": "REAL",
    "last_mod": "TEXT DEFAULT ''",  # ISO date typed in the old table
    "contents": "TEXT DEFAULT ''",
    "notes": "TEXT DEFAULT ''",
    "letter": "TEXT DEFAULT ''",  # last letter seen, only a hint
    "last_scan": "TEXT DEFAULT ''",
}

FILES_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    key TEXT PRIMARY KEY,   -- "<drive name>/<path on the drive>"
    drive TEXT NOT NULL,
    kind TEXT,
    folder_date TEXT,
    missing INTEGER DEFAULT 0,
    data TEXT NOT NULL      -- the whole entry as JSON
);
CREATE INDEX IF NOT EXISTS files_drive ON files (drive);
CREATE INDEX IF NOT EXISTS files_kind ON files (kind, folder_date);
"""


@dataclass
class Drive:
    name: str
    label: str = ""
    serial: str = ""
    location: str = ""
    status: str = ""
    size_gb: float | None = None
    used_gb: float | None = None
    free_gb: float | None = None
    last_mod: str = ""
    contents: str = ""
    notes: str = ""
    letter: str = ""
    last_scan: str = ""

    @property
    def title(self) -> str:
        """'Splash IV · Branco Estrela': the name plus what is written on the disk."""
        return f"{self.name} · {self.label}" if self.label else self.name


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    ddl = ", ".join(f"{name} {kind}" for name, kind in DRIVE_COLUMNS.items())
    conn.execute(f"CREATE TABLE IF NOT EXISTS drives ({ddl})")
    conn.executescript(FILES_SCHEMA)
    return conn


def list_drives(path: Path) -> list[Drive]:
    if not Path(path).exists():
        return []
    conn = connect(path)
    try:
        return [Drive(**dict(row)) for row in conn.execute("SELECT * FROM drives ORDER BY name")]
    finally:
        conn.close()


def get_drive(path: Path, name: str) -> Drive | None:
    return next((d for d in list_drives(path) if d.name == name), None)


def save_drive(path: Path, drive: Drive) -> None:
    columns = [f.name for f in fields(Drive)]
    conn = connect(path)
    try:
        with conn:
            conn.execute(
                f"INSERT OR REPLACE INTO drives ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                [getattr(drive, c) for c in columns],
            )
    finally:
        conn.close()


def file_counts(path: Path) -> dict[str, int]:
    """Indexed files per drive name (files marked missing are not counted)."""
    if not Path(path).exists():
        return {}
    conn = connect(path)
    try:
        rows = conn.execute("SELECT drive, COUNT(*) AS n FROM files WHERE missing = 0 GROUP BY drive")
        return {row["drive"]: row["n"] for row in rows}
    finally:
        conn.close()


# --- the old spreadsheet ---------------------------------------------------------------------------

_HEADERS = {
    "hd": "name", "descricao": "label", "letra": "letter", "tamanho": "size_gb", "ocupado": "used_gb",
    "livre": "free_gb", "status": "status", "ultima mod.": "last_mod", "localizacao": "location",
    "o que tem": "contents", "obs": "notes",
}


def _plain(text: str) -> str:
    import unicodedata

    stripped = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return stripped.strip().casefold()


def parse_gb(text: str) -> float | None:
    """'1,800.00' -> 1800.0, '1000 GB' -> 1000.0, '' -> None."""
    match = re.search(r"\d[\d,]*(?:\.\d+)?", text or "")
    return float(match.group().replace(",", "")) if match else None


def parse_date(text: str) -> str:
    """'15/08/2020' -> '2020-08-15'; anything else is kept as typed."""
    text = (text or "").strip()
    try:
        return datetime.strptime(text, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return text


def read_table(path: Path) -> list[Drive]:
    """The tab-separated sheet (HD, Descrição, Letra, Tamanho ...). Unknown columns are ignored."""
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    columns = {i: _HEADERS[_plain(h)] for i, h in enumerate(rows[0]) if _plain(h) in _HEADERS}
    if "name" not in columns.values():
        raise SystemExit(f"{path}: no 'HD' column in the first line.")
    drives = []
    for row in rows[1:]:
        values = {columns[i]: cell.strip() for i, cell in enumerate(row) if i in columns}
        if not values.get("name"):
            continue
        for key in ("size_gb", "used_gb", "free_gb"):
            values[key] = parse_gb(values.get(key, ""))
        values["last_mod"] = parse_date(values.get("last_mod", ""))
        values["contents"] = "" if values.get("contents") == "-" else values.get("contents", "")
        drives.append(Drive(**values))
    return drives


def import_table(db: Path, path: Path) -> tuple[int, int]:
    """Add the drives of the sheet. A drive that already exists keeps its serial and scan date. (added, updated)"""
    added = updated = 0
    for drive in read_table(path):
        old = get_drive(db, drive.name)
        if old:
            drive.serial, drive.last_scan = old.serial, old.last_scan
        save_drive(db, drive)
        added += not old
        updated += bool(old)
    return added, updated


# --- what is plugged in -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Mounted:
    root: Path
    serial: str
    volume_label: str
    total_gb: float
    free_gb: float


def mounted_volumes() -> list[Mounted]:
    """Every readable volume with its serial. Only implemented on Windows; elsewhere the list is empty."""
    if sys.platform != "win32":
        return []
    import ctypes
    import shutil
    import string

    kernel32 = ctypes.windll.kernel32
    found = []
    letters = kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not letters & (1 << i):
            continue
        root = f"{letter}:\\"
        label, serial = ctypes.create_unicode_buffer(261), ctypes.c_uint32()
        ok = kernel32.GetVolumeInformationW(root, label, 261, ctypes.byref(serial), None, None, None, 0)
        if not ok:
            continue
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        found.append(Mounted(Path(root), f"{serial.value:08X}", label.value, usage.total / 1e9, usage.free / 1e9))
    return found


def mounts_by_drive(db: Path, volumes: list[Mounted] | None = None) -> dict[str, Mounted]:
    """Drive name -> where it is plugged in now (matched by serial; drives without a serial yet never match)."""
    volumes = mounted_volumes() if volumes is None else volumes
    by_serial = {v.serial: v for v in volumes}
    return {d.name: by_serial[d.serial] for d in list_drives(db) if d.serial and d.serial in by_serial}


def refresh_from_mount(db: Path, drive: Drive, mount: Mounted) -> Drive:
    """Remember the serial, the letter and the real sizes of a plugged-in drive."""
    drive.serial = mount.serial
    drive.letter = mount.root.drive
    drive.size_gb = round(mount.total_gb)
    drive.free_gb = round(mount.free_gb)
    drive.used_gb = round(mount.total_gb - mount.free_gb)
    save_drive(db, drive)
    return drive


def mark_scanned(db: Path, name: str) -> None:
    drive = get_drive(db, name)
    if drive:
        drive.last_scan = date.today().isoformat()
        save_drive(db, drive)


def unregistered_volumes(db: Path, volumes: list[Mounted] | None = None) -> list[Mounted]:
    """Plugged-in volumes whose serial no registered drive has: the new disk waiting for a name.

    The disk Windows itself runs from is left out; it is not an archive."""
    known = {d.serial for d in list_drives(db) if d.serial}
    system = os.environ.get("SystemDrive", "").upper()
    return [
        v for v in (mounted_volumes() if volumes is None else volumes)
        if v.serial not in known and v.root.drive.upper() != system
    ]
