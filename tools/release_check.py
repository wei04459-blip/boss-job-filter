#!/usr/bin/env python3
"""Print or copy an allowlisted source release, excluding local task data."""
import argparse
import json
import re
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'boss-job-filter/scripts'))
from bootstrap import EXCLUDED


def release_files():
    fixed = ['README.md', 'LICENSE', 'install.py', '.gitignore', '.github/workflows/ci.yml',
             'docs/portability-validation.md', 'tools/release_check.py',
             'boss-job-filter/SKILL.md', 'boss-job-filter/LICENSE', 'boss-job-filter/requirements.txt']
    result = list(map(Path, fixed))
    for directory in ('boss-job-filter/scripts', 'boss-job-filter/references', 'boss-job-filter/agents', 'tests'):
        for path in (ROOT / directory).rglob('*'):
            if path.is_file() and not any(p in EXCLUDED for p in path.relative_to(ROOT).parts) and path.suffix != '.pyc':
                result.append(path.relative_to(ROOT))
    for rel in result:
        path = ROOT / rel
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'发布文件缺失或为软链接：{rel}')
        if path.suffix not in {'.py', '.md', '.mjs', '.txt', '.yaml', '.yml', '.json'} and path.name not in {'.gitignore', 'LICENSE'}:
            raise ValueError(f'发布目录内出现非源码文件：{rel}')
        content = path.read_text(encoding='utf-8')
        if re.search(r'(?:/Users|/home)/[A-Za-z0-9_.-]+/(?:Desktop|Documents|\.codex|\.cache)/', content):
            raise ValueError(f'发布文件包含作者本机路径或个人资料：{rel}')
    return sorted(set(result))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', type=Path)
    args = parser.parse_args()
    files = release_files()
    if args.stage:
        if args.stage.exists():
            raise ValueError('发布暂存目录已存在；请提供新的目录')
        args.stage.mkdir(parents=True)
        for rel in files:
            dest = args.stage / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, dest)
    print(json.dumps({'release_file_count': len(files), 'files': [str(p) for p in files], 'staged': str(args.stage) if args.stage else None}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
