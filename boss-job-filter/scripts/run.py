#!/usr/bin/env python3
"""Cross-platform launcher; the caller only needs a working base Python."""
from pathlib import Path
import subprocess
import sys
from bootstrap import python_in

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    python = python_in(root.parent / '.venv')
    if not python.is_file():
        sys.exit('环境尚未安装。先用本机 Python 运行此 skill 的 scripts/bootstrap.py。')
    sys.exit(subprocess.call([str(python), str(root / 'boss_jobs.py'), *sys.argv[1:]]))
