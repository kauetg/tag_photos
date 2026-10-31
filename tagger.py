"""Usage: python tagger.py <scan|doctor|...> [--dry-run] [--limit N] [--folder PATH]"""
import sys

from mediatagger.cli import main

if __name__ == "__main__":
    sys.exit(main())
