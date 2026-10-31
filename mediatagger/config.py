"""Load project configuration (TOML plus plain-text lists)."""
from __future__ import annotations

import csv
import fnmatch
import re
import tomllib
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"

# Folder names look like "20250122 Pereque": drop the date, keep the description.
_DATE_PREFIX = re.compile(r"^\d{8}\s*")


def normalize(text: str) -> str:
    """Lowercase and strip accents so 'São' matches 'sao'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


@dataclass(frozen=True)
class Location:
    match: str
    keyword: str
    country: str = ""
    city: str = ""
    sublocation: str = ""

    def as_dict(self) -> dict:
        return {
            "keyword": self.keyword,
            "country": self.country,
            "city": self.city,
            "sublocation": self.sublocation,
        }


@dataclass
class Config:
    media_root: Path
    data_dir: Path
    config_dir: Path
    exiftool: str = ""
    ffmpeg: str = ""
    save_every: int = 500
    quick_hash: bool = True
    kinds: dict[str, str] = field(default_factory=dict)  # ".arw" -> "raw"
    ignore_dirs: list[str] = field(default_factory=list)
    folders: list[str] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    def kind_of(self, filename: str) -> str | None:
        return self.kinds.get(Path(filename).suffix.lower())

    def is_ignored_dir(self, name: str) -> bool:
        folded = name.casefold()
        return any(fnmatch.fnmatch(folded, p.casefold()) for p in self.ignore_dirs)

    def find_location(self, folder_parts: tuple[str, ...]) -> Location | None:
        """First folder (top-down) whose description matches a locations.csv row wins."""
        for part in folder_parts:
            description = normalize(_DATE_PREFIX.sub("", part))
            best = None
            for loc in self.locations:
                pattern = r"\b" + re.escape(normalize(loc.match)) + r"\b"
                if re.search(pattern, description) and (
                    best is None or len(loc.match) > len(best.match)
                ):
                    best = loc
            if best:
                return best
        return None


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _read_folders(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = (ln.strip() for ln in path.read_text(encoding="utf-8").splitlines())
    return [ln for ln in lines if ln and not ln.startswith("#")]


def _read_locations(path: Path) -> list[Location]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [
            Location(
                match=row["match"].strip(),
                keyword=row["keyword"].strip(),
                country=(row.get("country") or "").strip(),
                city=(row.get("city") or "").strip(),
                sublocation=(row.get("sublocation") or "").strip(),
            )
            for row in csv.DictReader(f)
            if (row.get("match") or "").strip()
        ]


def load_config(
    config_dir: Path | None = None, media_root: str | None = None
) -> Config:
    """Merge config.toml with config.local.toml; `media_root` overrides both."""
    config_dir = Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
    raw = _read_toml(config_dir / "config.toml")
    raw.update(_read_toml(config_dir / "config.local.toml"))

    root = media_root or raw.get("media_root", "")
    if not root:
        raise SystemExit(
            "media_root is not set. Edit config/config.local.toml "
            "(see config.local.example.toml) or pass --media-root."
        )

    data_dir = Path(raw.get("data_dir", "data"))
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir

    kinds = {
        ext.lower(): kind
        for kind, exts in raw.get("extensions", {}).items()
        for ext in exts
    }

    return Config(
        media_root=Path(root),
        data_dir=data_dir,
        config_dir=config_dir,
        exiftool=raw.get("exiftool", ""),
        ffmpeg=raw.get("ffmpeg", ""),
        save_every=int(raw.get("save_every", 500)),
        quick_hash=bool(raw.get("quick_hash", True)),
        kinds=kinds,
        ignore_dirs=list(raw.get("ignore", {}).get("dirs", [])),
        folders=_read_folders(config_dir / "folders.txt"),
        locations=_read_locations(config_dir / "locations.csv"),
    )
