"""Deterministic job filters. Unknown evidence never becomes a pass."""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata

PASS, UNKNOWN, FAIL = "通过", "待确认", "排除"
DEGREES = {"初中及以下", "中专/中技", "高中", "大专", "本科", "硕士", "博士", "学历不限"}
EXPERIENCES = {"在校生", "应届生", "经验不限", "1年以内", "1-3年", "3-5年", "5-10年", "10年以上"}
SCALES = {"0-20人", "20-99人", "100-499人", "500-999人", "1000-9999人", "10000人以上"}
UNITS = {"月", "天", "小时", "年"}


def norm(value):
    value = unicodedata.normalize("NFKC", str(value or "")).strip()
    value = re.sub(r"[~～—–−]", "-", re.sub(r"\s+", "", value))
    return re.sub(r"(?<=[\d岁])至(?=\d)", "-", value)


def canonical(value, field):
    value = norm(value)
    aliases = {
        "degree": {"不限": "学历不限", "专科": "大专", "中专": "中专/中技", "中技": "中专/中技"},
        "experience": {"不限": "经验不限", "在校生(实习)": "在校生", "应届毕业生": "应届生", "应届生(校招)": "应届生", "1年以下": "1年以内", "10年及以上": "10年以上"},
        "scale": {"10000+人": "10000人以上", "10000人及以上": "10000人以上", "20人以下": "0-20人"},
    }
    return aliases.get(field, {}).get(value, value)


def validate_config(config):
    allowed = {"mode", "city", "keywords", "limit", "age", "salary", "degree", "experience", "scale"}
    extra = set(config) - allowed
    if extra:
        raise ValueError("未知配置项：" + ", ".join(sorted(extra)))
    c = dict(config)
    c.setdefault("mode", "个人求职")
    c.setdefault("limit", 150)
    if c["mode"] not in {"个人求职", "市场调研"}:
        raise ValueError("mode 只能为个人求职或市场调研")
    if not isinstance(c.get("city"), str) or not c["city"].strip():
        raise ValueError("请明确指定一个城市")
    c["city"] = c["city"].strip()
    if not isinstance(c.get("keywords"), list) or not c["keywords"] or any(not isinstance(k, str) or not k.strip() for k in c["keywords"]):
        raise ValueError("keywords 必须是非空岗位关键词列表")
    c["keywords"] = list(dict.fromkeys(k.strip() for k in c["keywords"]))
    if type(c["limit"]) is not int or not 1 <= c["limit"] <= 150:
        raise ValueError("limit 必须是 1–150 的整数（原始岗位去重上限）")
    if c.get("age") is not None and (type(c["age"]) is not int or c["age"] <= 0):
        raise ValueError("age 应为求职者年龄的正整数，或 null 表示不筛年龄")
    for field, options in [("degree", DEGREES), ("experience", EXPERIENCES), ("scale", SCALES)]:
        raw = c.get(field, [])
        if not isinstance(raw, list) or any(not isinstance(v, str) for v in raw):
            raise ValueError(f"{field} 必须是档位列表，留空列表表示不筛")
        c[field] = list(dict.fromkeys(canonical(v, field) for v in raw))
        invalid = set(c[field]) - options
        if invalid:
            raise ValueError(f"{field} 档位不明确：{', '.join(invalid)}；可用：{', '.join(sorted(options))}")
    salary = c.get("salary")
    if salary is not None:
        if not isinstance(salary, dict) or set(salary) - {"min", "max", "unit"}:
            raise ValueError("salary 使用 min/max/unit，金额以元为单位")
        if salary.get("unit") not in UNITS:
            raise ValueError("salary.unit 必须明确为月、天、小时或年")
        if salary.get("min") is None and salary.get("max") is None:
            raise ValueError("薪资至少需要一个金额边界")
        for key in ["min", "max"]:
            v = salary.get(key)
            if v is not None and (type(v) not in (int, float) or not math.isfinite(v) or v < 0):
                raise ValueError("薪资金额应为非负有限数字")
        if salary.get("min", 0) is not None and salary.get("max") is not None and salary.get("min", 0) > salary["max"]:
            raise ValueError("薪资下限不能高于上限")
    return c


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def content_hash(job):
    return digest({k: job.get(k) for k in ["job_id", "title", "company", "city", "salary", "degree", "experience", "scale", "jd", "detail_fields", "detail_status"]})


def decision(status, reason, evidence=""):
    return {"status": status, "reason": reason, "evidence": evidence}


def parse_salary(raw):
    text = norm(raw).upper()
    result = {"raw": raw or "", "min": None, "max": None, "unit": None, "months": None, "error": None}
    if not text or re.search(r"面议|提成|综合|保底|底薪.*[+＋]|[\ue000-\uf8ff]", text):
        result["error"] = "薪资缺失、含不确定组成或无法可靠读取"
        return result
    months = re.search(r"[·•](\d+)薪", text)
    if months:
        result["months"] = int(months.group(1))
        text = text[:months.start()] + text[months.end():]
    units = [u for u, pattern in [("小时", r"/小时|/时|时薪"), ("天", r"/天|/日|日薪"), ("年", r"/年|年薪"), ("月", r"/月|月薪")] if re.search(pattern, text)]
    if len(units) > 1:
        result["error"] = "同一薪资字段包含多个计薪单位"
        return result
    unit = units[0] if units else ("月" if re.search(r"K|千|万", text) else None)
    text = re.sub(r"(?:月薪|年薪|日薪|时薪|底薪)", "", text)
    text = re.sub(r"(?:元)?/(?:小时|时|天|日|月|年)$", "", text)
    text = re.sub(r"元$", "", text)
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(K|千|万)?(?:-(\d+(?:\.\d+)?)(K|千|万)?)?(以上|以下|起)?", text)
    if not match or unit is None:
        result["error"] = "薪资金额或计薪单位不明确"
        return result
    a, ua, b, ub, bound = match.groups()
    factors = {None: 1, "K": 1000, "千": 1000, "万": 10000}
    low = float(a) * factors[ua or ub]
    high = float(b) * factors[ub or ua] if b else low
    if low > high or (b and bound):
        result["error"] = "薪资区间存在歧义"
        return result
    if bound in ("以上", "起"):
        high = None
    elif bound == "以下":
        low = 0
    result.update(min=low, max=high, unit=unit)
    return result


def salary_decision(raw, requirement):
    parsed = parse_salary(raw)
    if not requirement:
        return decision(PASS, "未启用薪资条件"), parsed
    if parsed["error"]:
        return decision(UNKNOWN, parsed["error"], raw), parsed
    if parsed["unit"] != requirement["unit"]:
        return decision(UNKNOWN, "计薪单位不同，未作假定换算", raw), parsed
    low = requirement.get("min") if requirement.get("min") is not None else 0
    high = requirement.get("max") if requirement.get("max") is not None else math.inf
    overlap = max(low, parsed["min"]) <= min(high, parsed["max"] if parsed["max"] is not None else math.inf)
    return decision(PASS if overlap else FAIL, "薪资区间有交集" if overlap else "薪资区间无交集", raw), parsed


def age_decision(jd, age):
    if age is None:
        return decision(PASS, "未启用年龄条件")
    evidence = []
    limits = []
    unlimited = False
    for sentence in re.split(r"[。；;\n]", jd or ""):
        s = norm(sentence)
        if not re.search(r"年龄|岁", s):
            continue
        # Team/client ages are not applicant requirements.
        if re.search(r"平均年龄|团队年龄|客户|用户|儿童|幼儿|学生年龄|服务对象", s):
            continue
        evidence.append(sentence.strip())
        if re.search(r"放宽|优先|左右|原则|建议|最佳|最好|优选|或|例外", s):
            return decision(UNKNOWN, "年龄表述有弹性或例外，需要确认", sentence.strip())
        if re.search(r"年龄不限|不限年龄|无年龄限制|不限制年龄|不设年龄", s):
            unlimited = True
            continue
        p = re.sub(r"周岁", "岁", s)
        found = False
        range_match = re.search(r"(\d{1,3})岁?-(\d{1,3})岁", p)
        if range_match:
            a, b = map(int, range_match.groups())
            limits.append((a, b))
            p = p[:range_match.start()] + p[range_match.end():]
            found = True
        patterns = [
            (r"(?:不得超过|不能超过|不可超过|不超过|不大于|不高于|至多|最高)(\d{1,3})岁", lambda n: (0, n)),
            (r"(?:不得低于|不能低于|不低于|不小于|不少于|至少|年满)(\d{1,3})岁", lambda n: (n, math.inf)),
            (r"(?:未满|不满|小于|低于)(\d{1,3})岁", lambda n: (0, n - 1)),
            (r"(?:超过|大于|高于)(\d{1,3})岁", lambda n: (n + 1, math.inf)),
            (r"(\d{1,3})岁(?:以下|以内|及以下)", lambda n: (0, n)),
            (r"(\d{1,3})岁(?:以上|及以上)", lambda n: (n, math.inf)),
        ]
        for pattern, convert in patterns:
            for m in re.finditer(pattern, p):
                limits.append(convert(int(m.group(1))))
                found = True
            # Consume complete phrases so “不超过” is not matched again as “超过”.
            p = re.sub(pattern, " ", p)
        if not found:
            return decision(UNKNOWN, "年龄文字不能明确解析为任职限制", sentence.strip())
    quote = "；".join(evidence)
    if unlimited and limits:
        return decision(UNKNOWN, "年龄限制与年龄不限相互冲突", quote)
    if unlimited:
        return decision(PASS, "岗位明确不限制年龄", quote)
    if not limits:
        return decision(UNKNOWN, "岗位未写明确年龄要求")
    low = max(x[0] for x in limits)
    high = min(x[1] for x in limits)
    if low > high:
        return decision(UNKNOWN, "岗位年龄条件相互冲突", quote)
    return decision(PASS if low <= age <= high else FAIL, "年龄符合明确限制" if low <= age <= high else "年龄不符合明确限制", quote)


def field_decision(raw, accepted, field, detail_raw=""):
    if not accepted:
        return decision(PASS, "未启用此条件")
    if detail_raw and raw and canonical(detail_raw, field) != canonical(raw, field):
        return decision(UNKNOWN, "列表与详情字段不一致", f"列表：{raw}；详情：{detail_raw}")
    raw = raw or detail_raw
    if not raw:
        return decision(UNKNOWN, "未获取到此字段")
    options = {"degree": DEGREES, "experience": EXPERIENCES, "scale": SCALES}[field]
    value = canonical(raw, field)
    if value not in options:
        return decision(UNKNOWN, "字段不能明确对应筛选档位", raw)
    return decision(PASS if value in accepted else FAIL, "符合指定档位" if value in accepted else "不属于指定档位", raw)


def validate_reviews(reviews, config, jobs):
    if not reviews:
        return {}
    if reviews.get("config_hash") != digest(config):
        raise ValueError("复核文件对应的筛选条件已改变，请重新复核")
    indexed = {j["job_id"]: j for j in jobs}
    result = {}
    for item in reviews.get("jobs", []):
        jid = item.get("job_id")
        if jid not in indexed or jid in result:
            raise ValueError("复核文件有不存在或重复的岗位标识")
        job = indexed[jid]
        if item.get("content_hash") != content_hash(job):
            raise ValueError(f"岗位 {jid} 内容已改变，请重新复核")
        if item.get("checked_requirements") is not True:
            raise ValueError("复核必须明确 checked_requirements=true，检查职位正文与列表条件是否冲突")
        role = item.get("role", {})
        if role.get("status") not in {PASS, UNKNOWN, FAIL} or not isinstance(role.get("reason"), str) or not role["reason"].strip():
            raise ValueError("复核需要岗位方向结论及理由")
        quote = role.get("evidence", "")
        if (role["status"] != UNKNOWN and not quote) or (quote and quote not in (job.get("jd") or "")):
            raise ValueError("岗位方向的判断依据必须逐字出自该岗位 JD")
        for conflict in item.get("conflicts", []):
            if conflict.get("field") not in {"age", "salary", "degree", "experience", "scale", "city"}:
                raise ValueError("冲突字段无效")
            if not conflict.get("evidence") or conflict["evidence"] not in (job.get("jd") or ""):
                raise ValueError("冲突证据必须逐字出自岗位 JD")
        if "summary" in item and (not isinstance(item["summary"], str) or len(item["summary"]) > 300):
            raise ValueError("职责摘要应为不超过 300 字的字符串")
        result[jid] = item
    return result


def evaluate(job, config, review=None):
    details = job.get("detail_fields") or {}
    checks = {}
    city = job.get("city") or ""
    checks["city"] = decision(PASS if norm(city) == norm(config["city"]) else FAIL if city else UNKNOWN, "实际城市匹配" if norm(city) == norm(config["city"]) else "实际城市不同" if city else "城市未获取到", city)
    checks["salary"], parsed = salary_decision(job.get("salary", ""), config.get("salary"))
    for field in ["degree", "experience", "scale"]:
        checks[field] = field_decision(job.get(field, ""), config[field], field, details.get(field, ""))
    complete = job.get("detail_status") == "complete" and bool(job.get("jd"))
    checks["detail"] = decision(PASS if complete else UNKNOWN, "已读取职位描述" if complete else job.get("detail_error") or "职位详情尚未完整读取")
    checks["age"] = age_decision(job.get("jd", "") if complete else "", config.get("age"))
    if not complete and config.get("age") is not None:
        checks["age"] = decision(UNKNOWN, "详情未完整读取，无法判断年龄")
    checks["role"] = review["role"] if review and complete else decision(UNKNOWN, "岗位职责与条件正文尚未复核")
    if review:
        for conflict in review.get("conflicts", []):
            field = conflict["field"]
            enabled = field == "city" or (config.get(field) is not None if field == "age" else bool(config.get(field)))
            if enabled:
                checks[field] = decision(UNKNOWN, "职位正文与条件存在冲突：" + conflict.get("reason", "需确认"), conflict["evidence"])
    statuses = {x["status"] for x in checks.values()}
    status = FAIL if FAIL in statuses else UNKNOWN if UNKNOWN in statuses else "符合"
    labels = {"city": "城市", "salary": "薪资", "degree": "学历", "experience": "经验", "scale": "企业规模", "age": "年龄", "detail": "详情", "role": "岗位方向"}
    return {**job, "salary_parsed": parsed, "checks": checks, "status": status,
            "jd_summary": (review or {}).get("summary") or ("原文摘录：" + job.get("jd", "")[:180] if job.get("jd") else "详情未读取"),
            "reason": "；".join(f"{labels[k]}：{v['reason']}" for k, v in checks.items() if v["status"] != PASS) or "所有启用条件均通过，已核对岗位职责", "content_hash": content_hash(job)}


def deduplicate(jobs, limit=150):
    result = {}
    for job in jobs:
        jid = job.get("job_id")
        if not jid:
            raise ValueError("岗位缺少可核对的 job_id，不能可靠去重")
        if jid in result:
            if job.get("detail_status") == "complete":
                result[jid] = job
        elif len(result) < limit:
            result[jid] = job
    return list(result.values())
