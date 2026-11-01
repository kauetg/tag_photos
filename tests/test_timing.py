from mediatagger.timing import duration, timing_line


def test_duration_switches_to_minutes_after_two():
    assert duration(31.4) == "31 s"
    assert duration(119) == "119 s"
    assert duration(180) == "3.0 min"


def test_timing_line_gives_the_per_file_time():
    assert timing_line(20, 32, "photos") == "20 photos in 32 s (1.6 s each, model loading not counted)"
    assert timing_line(0, 5, "videos") == "0 videos"  # nothing processed: no division by zero
