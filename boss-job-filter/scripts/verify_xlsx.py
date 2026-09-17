#!/usr/bin/env python3
"""Read-only check of the saved workbook against its reviewed source data."""
import argparse
import json
from pathlib import Path
import posixpath
from xml.etree import ElementTree as ET
import zipfile

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"x": MAIN}


def check(condition, message):
    if not condition:
        raise ValueError(message)


def verify(xlsx, report):
    with zipfile.ZipFile(xlsx) as z:
        check(z.testzip() is None, "Excel 文件压缩内容损坏")
        book = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {e.get("Id"): posixpath.normpath(posixpath.join("xl", e.get("Target"))) if not e.get("Target").startswith("/") else e.get("Target").lstrip("/") for e in rels}
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            strings = ["".join(el.itertext()) for el in ET.fromstring(z.read("xl/sharedStrings.xml"))]
        names = [s.get("name") for s in book.find("x:sheets", NS)]
        check(names == ["符合岗位", "待确认岗位", "原始岗位与判定", "任务说明"], "工作表名称或顺序错误")
        checked_links = 0
        for sheet in book.find("x:sheets", NS):
            name = sheet.get("name")
            target = targets[sheet.get(f"{{{REL}}}id")]
            root = ET.fromstring(z.read(target))
            cells = {}
            types = {}
            for cell in root.findall(".//x:sheetData/x:row/x:c", NS):
                ref, typ = cell.get("r"), cell.get("t")
                check(typ != "e", f"{name}!{ref} 含公式错误")
                val = cell.findtext("x:v", "", NS)
                if typ == "s":
                    val = strings[int(val)]
                elif typ == "inlineStr":
                    inline = cell.find("x:is", NS)
                    val = "".join(inline.itertext()) if inline is not None else ""
                elif typ in (None, "n") and val:
                    val = float(val)
                check("not implemented" not in str(val), f"{name}!{ref} 含不支持的函数结果")
                cells[ref], types[ref] = val, typ
            pane = root.find("x:sheetViews/x:sheetView/x:pane", NS)
            check(pane is not None and pane.get("ySplit") == ("3" if name == "任务说明" else "4"), f"{name} 未冻结表头")
            if name == "任务说明":
                for ref, expected in {"B9": len(report["jobs"]), "B10": report["summary"]["counts"]["符合"], "B11": report["summary"]["counts"]["待确认"], "B12": report["summary"]["counts"]["排除"], "B13": len(report["jobs"])}.items():
                    check(cells.get(ref) == expected, f"{name}!{ref} 汇总数量不一致")
                check(cells.get("B4") == report["summary"]["delivery_status"], "交付状态不一致")
                continue
            jobs = [j for j in report["jobs"] if name == "原始岗位与判定" or j["status"] == ("符合" if name == "符合岗位" else "待确认")]
            ids = [v for r, v in cells.items() if r.startswith("X") and r[1:].isdigit() and int(r[1:]) >= 5 and v]
            check(ids == [j["job_id"] for j in jobs], f"{name} 岗位数量、顺序或标识不一致")
            if jobs:
                check(root.find("x:tableParts", NS) is not None, f"{name} 缺少可筛选表格")
                relpath = posixpath.join(posixpath.dirname(target), "_rels", posixpath.basename(target) + ".rels")
                relationships = {e.get("Id"): e for e in ET.fromstring(z.read(relpath))}
                links = {e.get("ref"): e.get(f"{{{REL}}}id") for e in root.find("x:hyperlinks", NS)}
                check(len(links) == len(jobs), f"{name} 超链接数量不一致")
                headings = {v: r.rstrip("0123456789") for r, v in cells.items() if r.endswith("4") and r.rstrip("0123456789") + "4" == r}
                for n, job in enumerate(jobs, 5):
                    for col, key in [("B", "title"), ("D", "company"), ("E", "salary"), ("F", "degree"), ("G", "experience"), ("H", "scale"), ("I", "status")]:
                        actual = cells.get(f"{col}{n}", "")
                        expected = job.get(key) or ""
                        check(actual in (expected, "'" + expected), f"{name}!{col}{n} 与源数据不一致")
                    check(cells.get("B4") == "岗位名称" and cells.get("C4") == "岗位链接" and cells.get(f"C{n}") == "打开岗位", "岗位名称后缺少跳转链接")
                    relation = relationships[links[f"C{n}"]]
                    check(relation.get("Target") == job["url"] and relation.get("TargetMode") == "External", f"{name}!C{n} 链接指向错误")
                    for col, key in [("O", "min"), ("P", "max"), ("Q", "months")]:
                        expected = job["salary_parsed"].get(key)
                        check(cells.get(f"{col}{n}", "") == (expected if expected is not None else ""), f"{name}!{col}{n} 薪资数值错误")
                    for col, key in [("V", "collected_at"), ("W", "detail_collected_at")]:
                        if job.get(key):
                            check(types.get(f"{col}{n}") in (None, "n", "d") and bool(cells.get(f"{col}{n}")), f"{name}!{col}{n} 不是日期类型")
                    if name == "原始岗位与判定":
                        check(cells.get(f"{headings['完整职位描述']}{n}", "") in (job.get("jd", ""), "'" + job.get("jd", "")), "完整 JD 缺失或被截断")
                    checked_links += 1
    return {"verified": True, "sheets": names, "total_jobs": len(report["jobs"]), "links": checked_links, "counts": report["summary"]["counts"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.xlsx, json.loads(Path(args.report).read_text(encoding='utf-8'))), ensure_ascii=False, indent=2))
