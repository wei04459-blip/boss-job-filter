"""Local prerequisites and browser startup; no account or site probes."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies'


def settings():
    path = ROOT / '.runtime.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def artifact_runtime():
    config = settings()
    node = os.environ.get('BOSS_NODE') or config.get('node')
    packages = os.environ.get('BOSS_NODE_MODULES') or config.get('node_modules')
    if node or packages:
        if not node or not packages:
            raise RuntimeError('node 和 node_modules 必须成对配置')
        node, packages = Path(node).expanduser(), Path(packages).expanduser()
        if not node.is_file() or not (packages / '@oai/artifact-tool/package.json').is_file():
            raise RuntimeError('显式配置的 Codex 表格运行库不可用；请更新 .runtime.json，不能静默忽略')
        return node.resolve(), packages.resolve()
    for node in (DEFAULT_RUNTIME / 'node/bin/node', DEFAULT_RUNTIME / 'node/node.exe'):
        packages = DEFAULT_RUNTIME / 'node/node_modules'
        if node.is_file() and (packages / '@oai/artifact-tool/package.json').is_file():
            return node, packages
    return None


def browser_path(explicit=None):
    config = settings()
    explicit = explicit or os.environ.get('BOSS_CHROME') or config.get('chrome')
    if explicit:
        path = Path(explicit).expanduser()
        return str(path.resolve()) if path.is_file() else shutil.which(str(explicit))
    candidates = [shutil.which(x) for x in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome')]
    candidates += ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                   str(Path.home() / 'Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
                   '/Applications/Chromium.app/Contents/MacOS/Chromium']
    for base in ('LOCALAPPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)'):
        if os.environ.get(base):
            candidates.append(str(Path(os.environ[base]) / 'Google/Chrome/Application/chrome.exe'))
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), None)


def desktop_available():
    return platform.system() in ('Darwin', 'Windows') or bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))


def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def cdp_info(port):
    # A local proxy must not redirect the loopback readiness probe.
    with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/json/version', timeout=3) as response:
        data = json.load(response)
    if not data.get('webSocketDebuggerUrl') or not data.get('Browser'):
        raise RuntimeError('该端口不是有效的 Chrome 调试服务')
    return data


def doctor(port=9222, output_dir=None, offline=False, chrome=None):
    checks, errors = {}, []
    checks['python'] = sys.version.split()[0]
    if sys.version_info < (3, 10):
        errors.append('需要 Python 3.10+')
    checks['dependencies'] = {name: importlib.util.find_spec(name) is not None for name in ('requests', 'websocket', 'openpyxl')}
    if not all(checks['dependencies'].values()):
        errors.append('缺少 Python 依赖；运行 scripts/bootstrap.py')
    checks['platform'] = platform.system()
    checks['visible_desktop'] = desktop_available()
    if not checks['visible_desktop']:
        errors.append('需要可见桌面和交互式 Chrome；无桌面的云端容器不能完成登录与采集')
    checks['chrome'] = browser_path(chrome)
    if not checks['chrome']:
        errors.append('未找到 Chrome；安装官方 Chrome 或配置 BOSS_CHROME')
    missing = [name for name in ('scripts/vendor/boss_zhipin_scraper/scripts/boss_cdp_raw.py', 'scripts/vendor/boss_zhipin_scraper/data/city_codes.json', 'scripts/vendor/boss_zhipin_scraper/LICENSE') if not (ROOT / name).is_file()]
    checks['vendor_complete'] = not missing
    if missing:
        errors.append('skill 文件不完整：' + ', '.join(missing))
    try:
        runtime = artifact_runtime()
        checks['export_engine'] = 'artifact-tool' if runtime else 'openpyxl'
        if runtime:
            subprocess.run([str(runtime[0]), '--version'], check=True, capture_output=True, timeout=10)
        checks['preview'] = 'PNG' if runtime else '通过 Excel/WPS/LibreOffice 查看；不依赖 PNG 渲染器'
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        errors.append(str(exc))
    if output_dir:
        try:
            path = Path(output_dir).resolve()
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=path):
                pass
            checks['output_writable'] = str(path)
        except OSError as exc:
            errors.append(f'输出目录不可写：{exc}')
    checks['browser_ready'] = False
    if not offline:
        try:
            checks['browser_version'] = cdp_info(port)['Browser']
            if checks['dependencies']['requests'] and checks['dependencies']['websocket']:
                from browser import Session
                session = Session(port)
                try:
                    session.send('Browser.getVersion')
                    checks['browser_ready'] = True
                finally:
                    session.close()
        except Exception as exc:
            checks['browser_connection'] = str(exc)
    checks.update(environment_ready=not errors, errors=errors, port=port,
                  login='未向 BOSS 探测账号；首次登录需本人操作，实际可用性以搜索结果为准',
                  next='修复 errors 后重跑 doctor' if errors else 'collect（已有登录确认时）或 setup')
    return checks


def setup(port=9222, chrome=None, profile_dir=None):
    from browser import Session, upstream
    executable = browser_path(chrome)
    if not executable or not desktop_available():
        raise RuntimeError('需要已安装的 Chrome 和可见桌面；先执行 doctor')
    profile = Path(profile_dir).expanduser().resolve() if profile_dir else (
        Path.home() / '.boss-zhipin-scraper/chrome-profile' if port == 9222 else Path.home() / f'.boss-job-filter/chrome-{port}')
    if port_open(port):
        cdp_info(port)
        if not upstream.cdp_port_uses_profile(port, str(profile)):
            raise RuntimeError(f'端口 {port} 已被其他配置占用；选择空闲端口并在后续命令保持一致')
    else:
        profile.mkdir(parents=True, exist_ok=True)
        if list(profile.glob('Singleton*')):
            raise RuntimeError('专用浏览器可能已在另一端口打开；沿用该端口或先手动关闭专用窗口')
        process = upstream.launch_chrome([executable, f'--remote-debugging-port={port}',
            '--remote-debugging-address=127.0.0.1', f'--user-data-dir={profile}',
            '--no-first-run', '--no-default-browser-check', '--remote-allow-origins=http://127.0.0.1:' + str(port)])
        for _ in range(30):
            try:
                cdp_info(port)
                break
            except Exception:
                if process.poll() is not None:
                    raise RuntimeError('Chrome 已退出；检查桌面权限和 profile 是否被占用')
                time.sleep(0.5)
        else:
            raise RuntimeError('Chrome 未能提供调试连接；保留窗口，请检查端口与启动状态')
    session = Session(port)
    try:
        targets = session.send('Target.getTargets')['result']['targetInfos']
        if not any('zhipin.com/' in target.get('url', '') for target in targets):
            session.send('Target.createTarget', {'url': 'https://www.zhipin.com/web/user/?ka=header-login', 'background': False})
    finally:
        session.close()
    return {'browser_ready': True, 'port': port, 'profile': str(profile), 'login': '请本人完成首次登录；已有本次登录确认时直接采集。'}
