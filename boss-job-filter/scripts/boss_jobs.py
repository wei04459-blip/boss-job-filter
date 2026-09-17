#!/usr/bin/env python3
"""Collect, review and export BOSS job records for the companion skill."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from rules import validate_config, validate_reviews, evaluate, digest, content_hash, deduplicate, FAIL

HERE = Path(__file__).resolve().parent
from runtime import artifact_runtime, DEFAULT_RUNTIME as RUNTIME


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def load_payload(path):
    payload = read_json(path)
    if payload.get("schema_version") != 1:
        raise ValueError("不支持的原始数据版本")
    payload["config"] = validate_config(payload["config"])
    if len(payload["jobs"]) > payload["config"]["limit"]:
        raise ValueError("原始文件超过本次任务数量上限")
    if len(deduplicate(payload["jobs"])) != len(payload["jobs"]):
        raise ValueError("原始文件包含重复岗位，请先核对采集文件")
    return payload


def prepare(payload, output):
    config = payload["config"]
    tasks = []
    for job in payload["jobs"]:
        initial = evaluate(job, config)
        if job.get("detail_status") != "complete":
            continue
        tasks.append({k: job.get(k) for k in ["job_id", "title", "company", "city", "salary", "degree", "experience", "scale", "jd", "url"]} | {
            "content_hash": content_hash(job), "automatic_checks": initial["checks"]})
    result = {"config": config, "config_hash": digest(config), "jobs": tasks}
    write_json(output, result)
    return {"review_count": len(tasks), "total": len(payload["jobs"]), "file": str(output)}


def report_data(payload, reviews=None):
    config = payload["config"]
    indexed = validate_reviews(reviews, config, payload["jobs"])
    jobs = [evaluate(j, config, indexed.get(j["job_id"])) for j in payload["jobs"]]
    counts = {status: sum(j["status"] == status for j in jobs) for status in ["符合", "待确认", "排除"]}
    assert sum(counts.values()) == len(jobs)
    complete_details = sum(j.get("detail_status") == "complete" for j in jobs)
    reviewed = len(indexed)
    coverage = payload["collection"].get("status", "unknown")
    success = coverage in {"target_reached", "result_end"}
    outstanding = sum(j.get("detail_status") == "complete" and j["job_id"] not in indexed for j in jobs)
    role_pending = sum(j["checks"]["role"]["status"] == "待确认" and j["status"] != FAIL for j in jobs)
    return {"schema_version": 1, "config": config, "collection": payload["collection"], "jobs": jobs,
        "summary": {"total": len(jobs), "counts": counts, "detail_complete": complete_details,
            "detail_incomplete": len(jobs) - complete_details, "reviewed": reviewed, "review_outstanding": outstanding, "role_pending": role_pending,
            "delivery_status": "完成" if success and complete_details == len(jobs) and outstanding == 0 else "部分完成",
            "coverage": "本次城市、关键词和筛选条件下实际获取的样本，不代表全市场岗位"}}


def export_xlsx(data_path, output, preview=False):
    data = read_json(data_path)
    runtime = artifact_runtime()
    if runtime:
        node, packages = runtime
        args = [str(node), str(HERE / 'export_workbook.mjs'), str(data_path), str(output)]
        if preview:
            args.append('--preview')
        subprocess.run(args, env={**os.environ, 'BOSS_NODE_MODULES': str(packages)}, check=True, timeout=180)
        from xlsx_links import add_links
        add_links(output, data)
    else:
        from export_portable import export
        export(data, output)
        if preview:
            print('未安装 Codex 图像渲染库；已生成 Excel，请通过表格应用查看四张工作表。', file=sys.stderr)
    from verify_xlsx import verify
    result = verify(output, data)
    result['export_engine'] = 'artifact-tool' if runtime else 'openpyxl'
    write_json(Path(output).with_suffix('.verification.json'), result)
    return result


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="BOSS 定向筛选：采集、复核、导出 Excel")
    subs = parser.add_subparsers(dest="command", required=True)
    for command in ["setup", "doctor"]:
        s = subs.add_parser(command)
        s.add_argument("--port", type=int, default=9222)
        s.add_argument('--browser-path')
        if command == 'doctor':
            s.add_argument('--output-dir')
            s.add_argument('--offline', action='store_true')
        else:
            s.add_argument('--profile-dir')
    s = subs.add_parser("collect")
    s.add_argument("--config", required=True)
    s.add_argument("--output", required=True)
    s.add_argument("--port", type=int, default=9222)
    s.add_argument("--pages", type=int, default=10)
    s = subs.add_parser("details")
    s.add_argument("--input", required=True)
    s.add_argument("--port", type=int, default=9222)
    s.add_argument("--max-details", type=int)
    s.add_argument("--resume-confirmed", action="store_true", help="仅在用户确认已人工恢复登录或验证后使用")
    s = subs.add_parser("prepare")
    s.add_argument("--input", required=True)
    s.add_argument("--output", required=True)
    s = subs.add_parser("report")
    s.add_argument("--input", required=True)
    s.add_argument("--reviews")
    s.add_argument("--output", required=True, help="Excel 输出路径，以 .xlsx 结尾")
    s.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    try:
        if hasattr(args, 'port') and not 1024 <= args.port <= 65535:
            raise ValueError('调试端口必须在 1024–65535 之间')
        if args.command in {"doctor", "setup"}:
            from runtime import setup, doctor
            if args.command == "setup":
                result = setup(args.port, args.browser_path, args.profile_dir)
            else:
                result = doctor(args.port, args.output_dir, args.offline, args.browser_path)
        elif args.command == "collect":
            from browser import collect
            if not 1 <= args.pages <= 10:
                raise ValueError("每次最多 10 页，请输入 1–10")
            if Path(args.output).exists():
                raise ValueError("采集文件已存在，请指定新的输出位置，避免覆盖先前结果")
            payload = collect(validate_config(read_json(args.config)), args.output, args.port, args.pages)
            result = {"total": len(payload["jobs"]), "collection": payload["collection"], "file": args.output}
        elif args.command == "details":
            from browser import collect_details
            if args.max_details is not None and args.max_details < 1:
                raise ValueError("max-details 必须为正整数")
            payload = collect_details(load_payload(args.input), args.input, args.port, args.max_details, args.resume_confirmed)
            result = {"total": len(payload["jobs"]), "detail_complete": sum(j["detail_status"] == "complete" for j in payload["jobs"]), "collection": payload["collection"]}
        elif args.command == "prepare":
            result = prepare(load_payload(args.input), args.output)
        else:
            output = Path(args.output).resolve()
            if output.suffix.lower() != ".xlsx":
                raise ValueError("表格输出路径必须以 .xlsx 结尾")
            data = report_data(load_payload(args.input), read_json(args.reviews) if args.reviews else None)
            data_path = output.with_suffix(".report.json")
            write_json(data_path, data)
            verification = export_xlsx(data_path, output, args.preview)
            result = {"file": str(output), **data["summary"], 'verification': verification}
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        if args.command == 'doctor' and (not result['environment_ready'] or (not args.offline and not result['browser_ready'])):
            return 2
        if args.command == "collect" and result["collection"]["status"] not in {"target_reached", "result_end", "page_limit"}:
            return 2
        if args.command == "details" and result["collection"]["detail_status"] != "complete":
            return 2
        return 0
    except (ValueError, OSError, RuntimeError, ImportError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
