from mediatagger.config import Location, normalize


def test_normalize_strips_accents():
    assert normalize("São Paulo") == "sao paulo"


def test_location_match_is_word_based_and_longest_wins(cfg):
    cfg.locations.append(Location("Sao Paulo Mercado", "Location|X", "", "", ""))
    assert cfg.find_location(("20241227 Sao Paulo Mercado",)).keyword == "Location|X"
    # "Perequezinho" must not match "Pereque" (whole words only).
    assert cfg.find_location(("20250101 Perequezinho",)) is None


def test_location_found_in_deeper_folder(cfg):
    loc = cfg.find_location(("20250101 Viagem", "Pereque"))
    assert loc.sublocation == "Pereque"


def test_date_range_shortest_wins(cfg):
    assert cfg.find_location_by_date("20250101").sublocation == "Newyear"
    assert cfg.find_location_by_date("20250115").keyword == "Location|Brazil|Casa"
    assert cfg.find_location_by_date("20250201") is None
    assert cfg.find_location_by_date(None) is None
    assert cfg.find_location_by_date("20251399") is None  # not a real date


def test_ignored_dirs(cfg):
    assert cfg.is_ignored_dir("Malaysia24-v13 Previews.lrdata")
    assert cfg.is_ignored_dir("old lightroom catalogs")
    assert not cfg.is_ignored_dir("20250122 Pereque")
