import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mediatagger.config import load_config  # noqa: E402


@pytest.fixture
def media(tmp_path):
    """Synthetic drive: dated folders, a Lightroom catalog folder and non-media files."""
    root = tmp_path / "drive"
    files = {
        "20250122 Pereque/a.ARW": b"raw-a" * 100,
        "20250122 Pereque/b.jpg": b"jpg-b" * 100,
        "20250122 Pereque/clip.mp4": b"v" * 300_000,
        "20241227 Chegada Ilhabela/c.DNG": b"dng-c" * 100,
        "20241227 Sao Paulo Mercado/d.jpg": b"jpg-d" * 100,
        "Malaysia24/Malaysia24-v13 Previews.lrdata/p.jpg": b"preview",
        "Malaysia24/Old Lightroom Catalogs/old.jpg": b"old",
        "20250101 Casinha/notes.txt": b"not media",
        "20250101 Casinha/e.mov": b"mov-e" * 100,
    }
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


@pytest.fixture
def cfg(tmp_path, media):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        f'''drive = "Test"
media_root = "{media.as_posix()}"
data_dir = "{(tmp_path / "data").as_posix()}"
save_every = 2
[extensions]
photo = [".jpg"]
raw = [".arw", ".dng"]
video = [".mp4", ".mov"]
[ignore]
dirs = ["*.lrdata", "Old Lightroom Catalogs"]
''',
        encoding="utf-8",
    )
    (config_dir / "folders.txt").write_text("# all\n*\n", encoding="utf-8")
    (config_dir / "locations.csv").write_text(
        "match,keyword,country,city,sublocation\n"
        "Pereque,Location|Brazil|Guaruja|Pereque,Brazil,Guaruja,Pereque\n"
        "Ilhabela,Location|Brazil|Ilhabela,Brazil,Ilhabela,\n"
        "Sao Paulo,Location|Brazil|Sao Paulo,Brazil,Sao Paulo,\n",
        encoding="utf-8",
    )
    (config_dir / "date_ranges.csv").write_text(
        "start,end,keyword,country,city,sublocation,note\n"
        "20250101,20250131,Location|Brazil|Casa,Brazil,Casa,,wide\n"
        "20250101,20250101,Location|Brazil|Casa|Newyear,Brazil,Casa,Newyear,narrow\n",
        encoding="utf-8",
    )
    return load_config(config_dir)
