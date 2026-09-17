import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'boss-job-filter/scripts'))
from bootstrap import copy_skill, SKILL
import runtime


class InstallationTests(unittest.TestCase):
    def test_source_copy_excludes_machine_state_and_preserves_vendor(self):
        with tempfile.TemporaryDirectory(prefix='boss 全新安装 ') as tmp:
            target = copy_skill(SKILL, Path(tmp) / 'installed skill')
            self.assertTrue((target / 'scripts/vendor/boss_zhipin_scraper/LICENSE').is_file())
            self.assertFalse((target / '.venv').exists())
            self.assertFalse((target / 'scripts/node_modules').exists())
            self.assertFalse((target / '.runtime.json').exists())
            self.assertFalse(list(target.rglob('*.pyc')))
            with self.assertRaises(ValueError):
                copy_skill(SKILL, target)
            # In-place dependency repair remains possible and the original remains intact.
            self.assertTrue((target / 'scripts/bootstrap.py').is_file())

    def test_no_artifact_runtime_is_optional_but_broken_override_is_error(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True), patch('runtime.settings', return_value={}), patch('runtime.DEFAULT_RUNTIME', Path(tmp)):
            self.assertIsNone(runtime.artifact_runtime())
            with patch.dict(os.environ, {'BOSS_NODE': '/nonexistent/node'}):
                with self.assertRaises(RuntimeError):
                    runtime.artifact_runtime()

    def test_doctor_reports_missing_chrome_and_never_contacts_site(self):
        with patch('runtime.browser_path', return_value=None), patch('runtime.cdp_info') as cdp:
            result = runtime.doctor(offline=True)
            self.assertFalse(result['environment_ready'])
            self.assertTrue(any('Chrome' in e for e in result['errors']))
            cdp.assert_not_called()

    def test_doctor_separates_desktop_and_browser_connection_from_login(self):
        with patch('runtime.desktop_available', return_value=False):
            result = runtime.doctor(offline=True)
            self.assertFalse(result['environment_ready'])
            self.assertFalse(result['browser_ready'])
            self.assertIn('本人', result['login'])

    def test_occupied_non_cdp_port_is_not_closed(self):
        # No real HTTP request or browser launch: the conflict must stop setup.
        with patch('runtime.browser_path', return_value=sys.executable), patch('runtime.desktop_available', return_value=True), patch('runtime.port_open', return_value=True), patch('runtime.cdp_info', side_effect=RuntimeError('occupied')), patch('browser.upstream.launch_chrome') as launch:
            with self.assertRaises(RuntimeError):
                runtime.setup(9234)
            launch.assert_not_called()

    def test_new_install_launcher_explains_missing_bootstrap(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = copy_skill(SKILL, Path(tmp) / 'skill')
            result = subprocess.run([sys.executable, str(target / 'scripts/run.py'), 'doctor'], capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('bootstrap.py', result.stderr)

    def test_session_initializes_lazy_upstream_dependencies_before_polling(self):
        import browser
        import websocket
        from unittest.mock import MagicMock
        ws = MagicMock()
        ws.recv.side_effect = websocket.WebSocketTimeoutException('idle')
        with patch.object(browser.upstream, 'websocket', None), patch('runtime.cdp_info', return_value={'webSocketDebuggerUrl': 'ws://127.0.0.1/test'}), patch('browser.websocket.create_connection', return_value=ws):
            session = browser.Session(9222)
            session.drain_events(0.001)
            session.close()

    def test_unknown_city_never_uses_upstream_online_fallback(self):
        import browser
        from rules import validate_config
        with patch('browser.upstream.load_live_city_maps') as online, patch('browser.Session') as session:
            with self.assertRaises(ValueError):
                browser.collect(validate_config({'city': '不存在城市', 'keywords': ['测试']}), 'unused.json')
            online.assert_not_called()
            session.assert_not_called()


if __name__ == '__main__':
    unittest.main()
