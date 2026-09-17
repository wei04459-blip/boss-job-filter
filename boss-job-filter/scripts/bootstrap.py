#!/usr/bin/env python3
"""Install a portable skill copy and its isolated Python environment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SKILL = Path(__file__).resolve().parents[1]
EXCLUDED = {'.venv', 'node_modules', '__pycache__', '.DS_Store', '.runtime.json'}


def python_in(venv):
    return Path(venv) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def copy_skill(source, destination):
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError(f'目标已存在，未覆盖：{destination}。升级前请检查旧版本并另行备份。')
    if source == destination or source in destination.parents:
        raise ValueError('安装目录不能位于源 skill 内')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Copy only distributable content; never copy an old virtual environment or session.
    with tempfile.TemporaryDirectory(prefix='.boss-install-', dir=destination.parent) as tmp:
        stage = Path(tmp) / 'skill'
        stage.mkdir()
        for name in ('SKILL.md', 'LICENSE', 'requirements.txt', 'scripts', 'references', 'agents'):
            path = source / name
            if path.is_dir():
                shutil.copytree(path, stage / name, ignore=shutil.ignore_patterns(*EXCLUDED, '*.pyc'))
            elif path.is_file():
                shutil.copy2(path, stage / name)
            else:
                raise ValueError(f'发布包缺少必要文件：{name}')
        stage.rename(destination)
    return destination


def bootstrap(skill):
    if sys.version_info < (3, 10):
        raise RuntimeError('需要 Python 3.10 或更新版本；优先使用 Codex 提供的 Python。')
    skill = Path(skill).resolve()
    req = skill / 'requirements.txt'
    venv = skill / '.venv'
    python = python_in(venv)
    uv = shutil.which('uv')
    if not python.exists():
        command = [uv, 'venv', '--python', sys.executable, str(venv)] if uv else [sys.executable, '-m', 'venv', str(venv)]
        subprocess.run(command, check=True, timeout=180)
    fingerprint = hashlib.sha256(req.read_bytes()).hexdigest()
    marker = venv / '.boss-requirements.sha256'
    probe = subprocess.run([str(python), '-c', 'import requests, websocket, openpyxl'], capture_output=True)
    if probe.returncode or not marker.exists() or marker.read_text().strip() != fingerprint:
        command = ([uv, 'pip', 'install', '--python', str(python)] if uv else [str(python), '-m', 'pip', 'install', '--disable-pip-version-check'])
        subprocess.run(command + ['-r', str(req)], check=True, timeout=300)
        subprocess.run([str(python), '-c', 'import requests, websocket, openpyxl'], check=True, timeout=30)
        marker.write_text(fingerprint, encoding='utf-8')
    return {'installed': True, 'skill': str(skill), 'python': str(python),
            'next': [str(python), str(skill / 'scripts/boss_jobs.py'), 'doctor'],
            'login': '首次登录由账号本人在专用 Chrome 中完成；安装不代表已登录。'}


def main(default_install=False):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, help='复制安装到此目录；已存在则停止')
    args = parser.parse_args()
    try:
        destination = args.destination
        if default_install and destination is None:
            destination = Path.home() / '.agents/skills/boss-job-filter'
        skill = copy_skill(SKILL, destination) if destination else SKILL
        print(json.dumps(bootstrap(skill), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'installed': False, 'error': str(exc), 'recovery': '修复所报依赖或网络问题后，在已复制的 skill 里重跑 scripts/bootstrap.py；不会删除已有数据。'}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
