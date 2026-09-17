#!/usr/bin/env python3
"""Install this checkout as a user skill, without overwriting another version."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'boss-job-filter/scripts'))
from bootstrap import main

if __name__ == '__main__':
    sys.exit(main(default_install=True))
