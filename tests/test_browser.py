import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "boss-job-filter/scripts"))
import browser
from rules import validate_config


def response(ids, has_more=True):
    return {"code": 0, "zpData": {"jobList": [{"encryptJobId": str(i), "jobName": "AI运营", "salaryDesc": "10-15K", "brandName": "验证公司", "cityName": "深圳", "jobDegree": "本科", "jobExperience": "3-5年", "brandScaleName": "100-499人"} for i in ids], "hasMore": has_more}}


class BrowserTests(unittest.TestCase):
    def collect_mock(self, responses, **config):
        cfg = validate_config({"city": "深圳", "keywords": ["AI运营"], **config})
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(browser, "Session", return_value=MagicMock()))
            stack.enter_context(patch.object(browser, "open_page", return_value=("target", "session")))
            cap = stack.enter_context(patch.object(browser, "Capture")).return_value
            cap.wait_next_response.side_effect = responses
            stack.enter_context(patch.object(browser, "page_problem", return_value={}))
            stack.enter_context(patch.object(browser.time, "sleep"))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            path = Path(tmp) / "raw.json"
            result = browser.collect(cfg, path)
            self.assertEqual(result, json.loads(path.read_text(encoding='utf-8')))
            return result, cap.wait_next_response.call_count

    def test_ten_pages_stop_at_150_unique(self):
        p, calls = self.collect_mock([response(range(n * 15, (n + 1) * 15)) for n in range(10)])
        self.assertEqual(len(p["jobs"]), 150)
        self.assertEqual(calls, 10)
        self.assertEqual(p["collection"]["status"], "target_reached")

    def test_later_page_restriction_preserves_data_and_stops(self):
        p, calls = self.collect_mock([response(range(15)), {"code": 37, "message": "访问异常"}, response(range(15, 30))])
        self.assertEqual(len(p["jobs"]), 15)
        self.assertEqual(calls, 2)
        self.assertEqual(p["collection"]["status"], "restricted")
        self.assertTrue(p["collection"]["issues"])

    def test_duplicate_page_does_not_claim_completion(self):
        p, calls = self.collect_mock([response(range(15)), response(range(15))])
        self.assertEqual(len(p["jobs"]), 15)
        self.assertEqual(p["collection"]["duplicates"], 15)
        self.assertEqual(p["collection"]["status"], "partial")

    def test_timeout_and_interrupt_keep_prior_rows(self):
        for second, status in [(None, "capture_timeout"), (KeyboardInterrupt(), "interrupted")]:
            p, calls = self.collect_mock([response(range(15)), second])
            self.assertEqual(len(p["jobs"]), 15)
            self.assertEqual(p["collection"]["status"], status)

    def test_empty_result_is_distinct_from_failure(self):
        p, _ = self.collect_mock([response([], False)])
        self.assertEqual(p["jobs"], [])
        self.assertEqual(p["collection"]["status"], "result_end")

    def test_multiple_queries_share_limit_and_record_coverage(self):
        p, calls = self.collect_mock([response(range(10), False), response(range(5, 20))], keywords=["AI运营", "AI产品运营"], limit=15)
        self.assertEqual(len(p["jobs"]), 15)
        self.assertEqual(p["collection"]["duplicates"], 5)
        self.assertEqual(len(p["collection"]["queries"]), 2)
        self.assertEqual(calls, 2)

    def test_capture_does_not_consume_another_tabs_response(self):
        cdp = MagicMock()
        url = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
        cdp.events = [
            {"method": "Network.requestWillBeSent", "sessionId": "other", "params": {"requestId": "r1", "request": {"url": url}}},
            {"method": "Network.loadingFinished", "sessionId": "other", "params": {"requestId": "r1"}},
            {"method": "Network.requestWillBeSent", "sessionId": "this", "params": {"requestId": "r2", "request": {"url": url}}},
            {"method": "Network.loadingFinished", "sessionId": "this", "params": {"requestId": "r2"}},
        ]
        capture = browser.Capture(cdp, "this")
        self.assertEqual(capture._next_completed(), "r2")
        capture._consumed.add("r2")
        self.assertIsNone(capture._next_completed())

    def test_resume_after_restriction_needs_explicit_recovery(self):
        p = {"collection": {"status": "target_reached", "detail_status": "restricted"}, "jobs": []}
        with patch.object(browser, "Session") as s, self.assertRaises(browser.CollectionError):
            browser.collect_details(p, "unused.json")
        s.assert_not_called()

    def test_search_filters_do_not_drop_intersecting_salary(self):
        cfg = validate_config({"city": "深圳", "keywords": ["AI运营"], "degree": ["本科", "学历不限"], "experience": ["3-5年"], "salary": {"min": 12000, "unit": "月"}})
        self.assertEqual(browser.search_filters(cfg), {"experience": "105"})

    def test_field_mapping_keeps_missing_distinct_from_unlimited(self):
        raw = response(["j"])["zpData"]["jobList"][0]
        a = browser.map_job(raw, "AI运营", "search")
        raw["jobDegree"], raw["jobExperience"] = "学历不限", ""
        b = browser.map_job(raw, "AI运营", "search")
        self.assertEqual((a["degree"], a["experience"]), ("本科", "3-5年"))
        self.assertEqual((b["degree"], b["experience"]), ("学历不限", ""))


if __name__ == "__main__":
    unittest.main()
