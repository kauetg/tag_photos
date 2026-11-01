"""A one-line timing summary for the long stages, so a small run tells you how long the whole archive will take."""
from __future__ import annotations


def duration(seconds: float) -> str:
    return f"{seconds:.0f} s" if seconds < 120 else f"{seconds / 60:.1f} min"


def timing_line(count: int, seconds: float, noun: str) -> str:
    """'20 photos in 31 s (1.6 s each)'. The per-file time is what to multiply by the size of the archive."""
    if not count:
        return f"0 {noun}"
    return f"{count} {noun} in {duration(seconds)} ({seconds / count:.1f} s each, model loading not counted)"
