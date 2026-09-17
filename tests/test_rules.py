import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "boss-job-filter/scripts"))
from rules import *
from boss_jobs import report_data


def config(**kw):
    return validate_config({"mode": "个人求职", "city": "深圳", "keywords": ["AI运营"], **kw})


def job(**kw):
    return {"job_id": "a123", "title": "AI运营", "company": "测试公司", "city": "深圳", "salary": "10-15K", "degree": "本科", "experience": "3-5年", "scale": "100-499人", "detail_status": "complete", "detail_fields": {}, "jd": "负责AI产品用户运营。任职要求：年龄35岁以下，本科，3-5年经验。", **kw}


class RulesTests(unittest.TestCase):
    def test_salary_units_and_overlap(self):
        for raw, lo, hi, unit in [("10–15K", 10000, 15000, "月"), ("1-1.5万/月", 10000, 15000, "月"), ("150-200元/天", 150, 200, "天"), ("年薪20-30万", 200000, 300000, "年"), ("50-80元/小时", 50, 80, "小时"), ("10K-15K", 10000, 15000, "月"), ("12K以上", 12000, None, "月")]:
            with self.subTest(raw=raw):
                p = parse_salary(raw)
                self.assertIsNone(p["error"])
                self.assertEqual((p["min"], p["max"], p["unit"]), (lo, hi, unit))
        req = {"min": 12000, "unit": "月"}
        self.assertEqual(salary_decision("10-15K", req)[0]["status"], PASS)
        self.assertEqual(salary_decision("8-10K", req)[0]["status"], FAIL)
        self.assertEqual(salary_decision("200元/天", req)[0]["status"], UNKNOWN)

    def test_salary_boundary_and_uncertainty(self):
        self.assertEqual(salary_decision("10-12K", {"min": 12000, "unit": "月"})[0]["status"], PASS)
        self.assertEqual(salary_decision("20K以上", {"max": 15000, "unit": "月"})[0]["status"], FAIL)
        for raw in ["面议", "底薪5K+提成", "综合10-20K", "\ue033-\ue041K", "10000", "15-10K", "20-30元/天/月"]:
            self.assertIsNotNone(parse_salary(raw)["error"], raw)
        p = parse_salary("10-15K·13薪")
        self.assertEqual(p["min"], 10000)
        self.assertEqual(p["months"], 13)

    def test_exact_buckets_and_missing_data(self):
        c = config(degree=["本科"], experience=["3-5年"], scale=["100-499人"])
        self.assertEqual(evaluate(job(degree="大专"), c)["status"], FAIL)
        self.assertEqual(evaluate(job(degree="不限"), c)["status"], FAIL)
        self.assertEqual(evaluate(job(experience="1-3年"), c)["status"], FAIL)
        self.assertEqual(evaluate(job(degree=""), c)["checks"]["degree"]["status"], UNKNOWN)
        self.assertEqual(evaluate(job(degree="本科", detail_fields={"degree": "大专"}), c)["checks"]["degree"]["status"], UNKNOWN)
        self.assertEqual(field_decision("不限", ["学历不限"], "degree")["status"], PASS)

    def test_age_boundaries(self):
        for text, age, status in [
            ("年龄18-35岁", 35, PASS), ("年龄18至35周岁", 36, FAIL),
            ("年龄35岁以下", 35, PASS), ("未满35岁", 35, FAIL),
            ("年龄不超过35岁", 35, PASS), ("年龄小于35岁", 35, FAIL),
            ("年龄不得超过35岁", 35, PASS), ("年龄至多35岁", 36, FAIL),
            ("年龄18岁至35岁", 35, PASS), ("年龄不小于18岁", 17, FAIL),
            ("年满18岁", 18, PASS), ("年龄不低于18岁", 17, FAIL),
            ("年龄不限", 50, PASS), ("本科，3年经验", 35, UNKNOWN),
            ("35岁以下，优秀者可放宽", 36, UNKNOWN),
            ("团队平均年龄26岁", 35, UNKNOWN),
            ("服务35岁以下客户", 40, UNKNOWN),
            ("年龄18-35岁。年龄40岁以上", 30, UNKNOWN),
            ("年龄不限。年龄35岁以下", 35, UNKNOWN),
        ]:
            with self.subTest(text=text):
                self.assertEqual(age_decision(text, age)["status"], status)
        self.assertEqual(age_decision("未写年龄", None)["status"], PASS)

    def test_fail_dominates_unknown(self):
        r = evaluate(job(degree="大专", jd="岗位未写年龄", detail_status="failed"), config(age=35, degree=["本科"]))
        self.assertEqual(r["status"], FAIL)
        self.assertEqual(r["checks"]["age"]["status"], UNKNOWN)

    def test_no_semantic_review_cannot_claim_pass(self):
        c = config()
        self.assertEqual(evaluate(job(), c)["status"], UNKNOWN)
        r = {"role": decision(PASS, "AI运营职责匹配", "负责AI产品用户运营。"), "checked_requirements": True}
        self.assertEqual(evaluate(job(), c, r)["status"], "符合")

    def test_review_rejects_stale_or_fabricated_evidence(self):
        c, j = config(), job()
        r = {"config_hash": digest(c), "jobs": [{"job_id": j["job_id"], "content_hash": content_hash(j), "checked_requirements": True, "role": decision(PASS, "职责匹配", "负责AI产品用户运营。")}]}
        self.assertEqual(len(validate_reviews(r, c, [j])), 1)
        bad = copy.deepcopy(r)
        bad["jobs"][0]["role"]["evidence"] = "不存在的招聘原文"
        with self.assertRaises(ValueError):
            validate_reviews(bad, c, [j])
        with self.assertRaises(ValueError):
            validate_reviews(r, config(age=35), [j])
        with self.assertRaises(ValueError):
            validate_reviews(r, c, [job(jd="岗位内容修改")])

    def test_requested_limit_and_deduplication(self):
        data = [job(job_id=f"job{i}") for i in range(200)]
        self.assertEqual(len(deduplicate(data + data, 150)), 150)
        newer = job(jd="完整描述", detail_status="complete")
        self.assertEqual(deduplicate([job(detail_status="pending"), newer])[0]["jd"], "完整描述")
        with self.assertRaises(ValueError):
            deduplicate([{"title": "同名岗位不能可靠去重"}])

    def test_config_rejects_ambiguous_or_ignored_conditions(self):
        for kw in [{"limit": 151}, {"limit": True}, {"experience": ["3年"]}, {"degree": "本科"}, {"degree": False}, {"salary": {"min": 12}}, {"salary": {"min": 15000, "max": 10000, "unit": "月"}}, {"unexpected_filter": "本科"}]:
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                config(**kw)

    def test_report_counts_and_failure_status(self):
        c = config(degree=["本科"])
        p = {"config": c, "jobs": [job(), job(job_id="b", degree="大专")], "collection": {"status": "capture_timeout"}}
        report = report_data(p)
        self.assertEqual(report["summary"]["counts"], {"符合": 0, "待确认": 1, "排除": 1})
        self.assertEqual(report["summary"]["delivery_status"], "部分完成")
        p["jobs"] = []
        self.assertEqual(report_data(p)["summary"]["delivery_status"], "部分完成")
        p["collection"]["status"] = "result_end"
        self.assertEqual(report_data(p)["summary"]["delivery_status"], "完成")

    def test_completed_review_can_leave_uncertain_jobs(self):
        c, j = config(age=35), job(jd="负责AI产品用户运营，具体职责边界面议。")
        r = {"config_hash": digest(c), "jobs": [{"job_id": j["job_id"], "content_hash": content_hash(j), "checked_requirements": True, "role": decision(UNKNOWN, "具体职责边界需确认")}]}
        p = {"config": c, "jobs": [j], "collection": {"status": "target_reached"}}
        report = report_data(p, r)
        self.assertEqual(report["summary"]["counts"][UNKNOWN], 1)
        self.assertEqual(report["summary"]["delivery_status"], "完成")

    def test_body_conflict_only_affects_enabled_fields(self):
        r = {"role": decision(PASS, "职责匹配"), "conflicts": [{"field": "degree", "evidence": "正文要求大专", "reason": "列表本科、正文大专"}]}
        self.assertEqual(evaluate(job(), config(), r)["status"], "符合")
        self.assertEqual(evaluate(job(), config(degree=["本科"]), r)["status"], UNKNOWN)


if __name__ == "__main__":
    unittest.main()
