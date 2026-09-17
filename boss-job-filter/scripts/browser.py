"""BOSS collector built on the pinned MIT upstream CDP implementation."""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import sys
import time
import requests
import websocket
from datetime import datetime
from urllib.parse import urlencode

from rules import deduplicate

VENDOR = Path(__file__).resolve().parent / "vendor/boss_zhipin_scraper"
spec = importlib.util.spec_from_file_location("boss_upstream", VENDOR / "scripts/boss_cdp_raw.py")
upstream = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = upstream
spec.loader.exec_module(upstream)


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


class CollectionError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Session(upstream.CDPSession):
    def __init__(self, cdp_port=9222):
        # The only direct HTTP request is to the local browser, never BOSS APIs.
        if not upstream.require_runtime_dependencies('requests', 'websocket'):
            raise RuntimeError('缺少浏览器依赖，请运行 scripts/bootstrap.py')
        from runtime import cdp_info
        self.cdp_port = cdp_port
        self.ws = websocket.create_connection(cdp_info(cdp_port)['webSocketDebuggerUrl'], timeout=20,
                                              http_no_proxy=['127.0.0.1', 'localhost'])
        self.mid = 0
        self.events = []

    def send(self, method, params=None, sid=None, timeout=20):
        self.ws.settimeout(timeout)
        response = super().send(method, params, sid, timeout)
        if "error" in response:
            raise CollectionError("browser_error", f"浏览器操作 {method} 失败：{response['error'].get('message', '')}")
        return response


class Capture(upstream.NetworkJoblistCapture):
    def _next_completed(self):
        requests, finished = [], set()
        for event in self.cdp.events:
            if event.get("sessionId") != self.sid:
                continue
            p = event.get("params", {})
            if event.get("method") == "Network.requestWillBeSent" and self._is_joblist_url(p.get("request", {}).get("url", "")):
                requests.append(p.get("requestId"))
            if event.get("method") == "Network.loadingFinished":
                finished.add(p.get("requestId"))
        return next((r for r in requests if r in finished and r not in self._consumed), None)


def open_page(session):
    # Use an actually visible page, avoiding the upstream Chrome 151 background regression.
    return upstream.create_page_session(session, background=False)


def close_page(session, target):
    if target:
        try:
            session.send("Target.closeTarget", {"targetId": target}, timeout=5)
        except (RuntimeError, TimeoutError, OSError, websocket.WebSocketException):
            pass


def page_problem(session, sid):
    state = session.eval_js("JSON.stringify({url:location.href,text:(document.body?.innerText||'').slice(0,5000)})", sid)
    state = json.loads(state) if state else {}
    url, text = state.get("url", ""), state.get("text", "")
    if "_security_check" in url or any(x in text for x in ["您的环境存在异常", "当前访问异常", "请完成安全验证", "请完成下方验证"]):
        raise CollectionError("restricted", "BOSS 要求安全验证，已停止；请在专用浏览器中人工处理")
    if "/web/user" in url or "/login" in url or "登录查看完整内容" in text:
        raise CollectionError("login_required", "BOSS 需要登录或正文被登录提示截断")
    return state


def check_response(data):
    if not isinstance(data, dict):
        raise CollectionError("response_error", "搜索响应不是有效对象")
    result = upstream.classify_login_probe_response(data)
    if result.status == upstream.LoginProbeStatus.RESTRICTED:
        raise CollectionError("restricted", "BOSS 返回访问限制，已停止，不自动重试")
    if result.status == upstream.LoginProbeStatus.UNAUTHENTICATED:
        raise CollectionError("login_required", "BOSS 未返回可用登录状态")
    if data.get("code") != 0 or not isinstance((data.get("zpData") or {}).get("jobList"), list):
        raise CollectionError("response_error", f"BOSS 搜索响应异常（code={data.get('code')}）")
    return data["zpData"]


def map_job(raw, keyword, search_url):
    mapped = upstream.map_api_job(raw)
    jid = raw.get("encryptJobId")
    if not jid or not mapped:
        return None
    return {
        "job_id": str(jid), "title": mapped["title"], "company": raw.get("brandName") or "",
        "city": raw.get("cityName") or "", "area": raw.get("areaDistrict") or "",
        "location": mapped["location"], "salary": mapped["salary"], "salary_source": mapped["salary_source"],
        "experience": raw.get("jobExperience") or "", "degree": raw.get("jobDegree") or "",
        "scale": mapped["company_scale"], "industry": mapped["company_industry"],
        "welfare": mapped["welfare"], "skills": mapped["skills"], "active_status": mapped["boss_active_status"],
        "url": mapped["job_link"], "source_keyword": keyword, "search_url": search_url,
        "collected_at": now(), "jd": "", "detail_status": "pending", "detail_fields": {},
        # Opaque detail navigation context stays in local raw data, never in Excel.
        "detail_context": {"security_id": mapped["security_id"], "lid": mapped["lid"]},
    }


def search_filters(config):
    result = {}
    maps = {"degree": upstream.DEGREE_MAP, "experience": upstream.EXPERIENCE_MAP, "scale": upstream.SCALE_MAP}
    for field, mapping in maps.items():
        values = config[field]
        if values:
            values = ["不限" if field == "degree" and v == "学历不限" else v for v in values]
            # A user-requested explicit unlimited degree cannot be expressed by a site filter.
            if field == "degree" and "不限" in values:
                continue
            result[field] = ",".join(mapping[v] for v in values)
    # Site salary buckets differ from interval overlap. Keep salary broad and compare exact values locally.
    return result


def collect(config, output, port=9222, max_pages=10):
    # Unknown cities must not activate the upstream's private-API fallback.
    cities, reverse = upstream.load_local_city_map()
    city_name = reverse.get(config['city'], config['city'])
    if city_name not in cities:
        raise ValueError('本地城市表未找到该城市，请确认城市名；未发出源站请求')
    city_code = cities[city_name]
    config = {**config, "city": city_name}
    payload = {"schema_version": 1, "config": config, "jobs": [], "collection": {
        "started_at": now(), "finished_at": None, "status": "running", "queries": [], "issues": [],
        "pages_received": 0, "duplicates": 0, "invalid_rows": 0, "limit": config["limit"],
        "salary_prefilter": "不使用平台薪资档位；按原始金额在本地比较", "detail_status": "not_started"}}
    save_json(output, payload)
    session, target = None, None
    try:
        session = Session(port)
        filters = search_filters(config)
        pages_left = min(max_pages, 10)
        for keyword in config["keywords"]:
            if not pages_left or len(payload["jobs"]) >= config["limit"]:
                break
            target, sid = open_page(session)
            capture = Capture(session, sid)
            capture.enable()
            url = "https://www.zhipin.com/web/geek/jobs?" + urlencode({"city": city_code, "query": keyword, **filters})
            query = {"keyword": keyword, "url": url, "pages": 0, "status": "running"}
            payload["collection"]["queries"].append(query)
            capture_timeout = 25
            for _ in range(pages_left):
                if query["pages"] == 0:
                    data = capture.wait_next_response(capture_timeout, trigger=lambda: session.send("Page.navigate", {"url": url}, sid))
                else:
                    time.sleep(12)
                    # The split layout puts a separately scrolling detail pane under
                    # fixed mouse coordinates. Scroll the document that contains
                    # the result list to trigger the site's normal next-page load.
                    session.eval_js("window.scrollTo(0, document.scrollingElement.scrollHeight); void 0;", sid)
                    data = capture.wait_next_response(capture_timeout)
                page_problem(session, sid)
                if data is None:
                    raise CollectionError("capture_timeout", "未捕获到下一批岗位，保留现有结果；不能据此认定搜索已全部完成")
                zp = check_response(data)
                query["pages"] += 1
                pages_left -= 1
                payload["collection"]["pages_received"] += 1
                seen = {j["job_id"] for j in payload["jobs"]}
                added = 0
                for raw in zp["jobList"]:
                    job = map_job(raw, keyword, url)
                    if not job:
                        payload["collection"]["invalid_rows"] += 1
                        continue
                    if job["job_id"] in seen:
                        payload["collection"]["duplicates"] += 1
                        continue
                    if len(payload["jobs"]) < config["limit"]:
                        payload["jobs"].append(job)
                        seen.add(job["job_id"])
                        added += 1
                save_json(output, payload)
                print(f"已接收 {payload['collection']['pages_received']} 页，去重后 {len(payload['jobs'])} 条", flush=True)
                if len(payload["jobs"]) >= config["limit"]:
                    query["status"] = "target_reached"
                    break
                if zp.get("hasMore") is False or not zp["jobList"]:
                    query["status"] = "result_end"
                    break
                if added == 0:
                    query["status"] = "duplicate_page"
                    payload["collection"]["issues"].append("返回重复页，已停止该关键词的翻页")
                    break
            if query["status"] == "running":
                query["status"] = "page_limit"
            close_page(session, target)
            target = None
        statuses = {q["status"] for q in payload["collection"]["queries"]}
        payload["collection"]["status"] = "target_reached" if len(payload["jobs"]) >= config["limit"] else "result_end" if len(payload["collection"]["queries"]) == len(config["keywords"]) and statuses == {"result_end"} else "page_limit" if "duplicate_page" not in statuses else "partial"
    except CollectionError as exc:
        payload["collection"]["status"] = exc.status
        payload["collection"]["issues"].append(str(exc))
    except KeyboardInterrupt:
        payload["collection"]["status"] = "interrupted"
        payload["collection"]["issues"].append("用户中断采集")
    except (OSError, TimeoutError, KeyError, ValueError, requests.RequestException, websocket.WebSocketException) as exc:
        payload["collection"]["status"] = "browser_error"
        payload["collection"]["issues"].append(f"浏览器或响应异常：{type(exc).__name__}")
    except Exception as exc:
        payload['collection']['status'] = 'browser_error'
        payload['collection']['issues'].append(f'程序异常，已停止：{type(exc).__name__}')
        raise
    finally:
        if session:
            close_page(session, target)
            session.close()
        for query in payload["collection"]["queries"]:
            if query["status"] == "running":
                query["status"] = payload["collection"]["status"]
        payload["collection"]["finished_at"] = now()
        save_json(output, payload)
    return payload


DETAIL_FIELDS_JS = """JSON.stringify((()=>{
 const t=s=>(document.querySelector(s)?.innerText||'').trim();
 const facts=[...document.querySelectorAll('.job-sider p')].map(x=>x.innerText.trim());
 const section=[...document.querySelectorAll('.job-detail-section, .job-sec')].find(e=>/职位描述/.test(e.querySelector('h3')?.innerText||''));
 const jd=section?.querySelector('.job-sec-text');
 const style=jd?getComputedStyle(jd):null;
 const experience=t('.job-primary .text-experiece');
 return {degree:t('.job-primary .text-degree'),experience:/天\\/周|个月/.test(experience)?'':experience,
 internship_schedule:/天\\/周|个月/.test(experience)?experience:'',
 scale:facts.find(x=>/^\\d+[\\d,~至—–-]*人(?:以上)?$/.test(x))||'',
 salary:t('.job-primary .salary'),title:t('.job-primary h1'),
 folded:!!jd && jd.scrollHeight>jd.clientHeight+2 && ['hidden','clip'].includes(style.overflowY),
 visible:!!jd && jd.getClientRects().length>0 && jd.clientHeight>0};
})())"""


def collect_details(payload, output, port=9222, max_details=None, resume_confirmed=False):
    blocked = next((v for v in [payload["collection"]["status"], payload["collection"].get("detail_status")] if v in {"restricted", "login_required"}), None)
    if blocked and not resume_confirmed:
        raise CollectionError(blocked, "上次采集被平台限制或登录阻断；用户确认人工恢复后，使用 --resume-confirmed 续采")
    session, target = None, None
    collection = payload["collection"]
    collection["detail_status"] = "running"
    count = 0
    try:
        session = Session(port)
        target, sid = open_page(session)
        for job in payload["jobs"]:
            if job.get("detail_status") == "complete":
                continue
            if max_details is not None and count >= max_details:
                break
            count += 1
            context = job.get("detail_context") or {}
            url = upstream.build_detail_url({"job_link": job["url"], **context})
            try:
                session.send("Page.navigate", {"url": url}, sid)
                extracted, fields = None, {}
                for attempt in range(5):
                    time.sleep(2)
                    state = page_problem(session, sid)
                    raw = session.eval_js(upstream.EXTRACT_DETAIL_JS, sid)
                    candidate = json.loads(raw) if raw else {}
                    raw_fields = session.eval_js(DETAIL_FIELDS_JS, sid)
                    fields = json.loads(raw_fields) if raw_fields else {}
                    # Never accept whole-body fallback or a folded/truncated description.
                    if candidate.get("jd") and fields.get("visible") and not fields.get("folded") and f"/job_detail/{job['job_id']}.html" in state.get("url", ""):
                        extracted = upstream.extract_detail_fields({**candidate, "page_text": ""}, min_length=20)
                        if extracted.get("jd"):
                            break
                if not extracted:
                    raise ValueError("未读取到该岗位完整且可见的职位描述")
                job.update(jd=extracted["jd"], detail_status="complete", detail_fields=fields, detail_error="", detail_collected_at=now())
                if extracted.get("boss_active_status"):
                    job["active_status"] = extracted["boss_active_status"]
            except ValueError as exc:
                job.update(detail_status="failed", detail_error=str(exc))
            save_json(output, payload)
            print(f"详情 {count}：{job['title']}（{job['detail_status']}）", flush=True)
            time.sleep(3)
        collection["detail_status"] = "complete" if all(j.get("detail_status") == "complete" for j in payload["jobs"]) else "partial"
    except CollectionError as exc:
        collection["detail_status"] = exc.status
        collection["issues"].append(str(exc))
    except KeyboardInterrupt:
        collection["detail_status"] = "interrupted"
        collection["issues"].append("用户中断详情采集")
    except (OSError, TimeoutError, KeyError, requests.RequestException, websocket.WebSocketException) as exc:
        collection["detail_status"] = "browser_error"
        collection["issues"].append("详情采集连接异常：" + type(exc).__name__)
    except Exception as exc:
        collection['detail_status'] = 'browser_error'
        collection['issues'].append(f'程序异常，已停止：{type(exc).__name__}')
        raise
    finally:
        if session:
            close_page(session, target)
            session.close()
        collection["details_finished_at"] = now()
        save_json(output, payload)
    return payload
