"""Add native links for the hyperlink capability missing in artifact-tool.

The workbook itself is authored by artifact-tool. Only hyperlink relationships
and their worksheet references are added here, using standard XLSX metadata.
"""
from pathlib import Path
import posixpath
import re
from xml.etree import ElementTree as ET
import zipfile

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("x", MAIN)
ET.register_namespace("r", REL)


def add_links(output, report):
    output = Path(output)
    with zipfile.ZipFile(output) as z:
        files = {n: z.read(n) for n in z.namelist()}
    book = ET.fromstring(files["xl/workbook.xml"])
    rels = ET.fromstring(files["xl/_rels/workbook.xml.rels"])
    targets = {e.get("Id"): posixpath.normpath(posixpath.join("xl", e.get("Target"))) if not e.get("Target").startswith("/") else e.get("Target").lstrip("/") for e in rels}
    groups = {"符合岗位": [j for j in report["jobs"] if j["status"] == "符合"], "待确认岗位": [j for j in report["jobs"] if j["status"] == "待确认"], "原始岗位与判定": report["jobs"]}
    total = 0
    for item in book.find(f"{{{MAIN}}}sheets"):
        jobs = groups.get(item.get("name"))
        if not jobs:
            continue
        filename = targets[item.get(f"{{{REL}}}id")]
        sheet = ET.fromstring(files[filename])
        if sheet.find(f"{{{MAIN}}}hyperlinks") is not None:
            raise ValueError("导出的文件已有链接，拒绝重复追加")
        relpath = posixpath.join(posixpath.dirname(filename), "_rels", posixpath.basename(filename) + ".rels")
        relationships = ET.fromstring(files[relpath]) if relpath in files else ET.Element(f"{{{PKG}}}Relationships")
        used = {e.get("Id") for e in relationships}
        links = ET.Element(f"{{{MAIN}}}hyperlinks")
        for n, job in enumerate(jobs):
            url = job["url"]
            if not re.fullmatch(r"https://www\.zhipin\.com/job_detail/[A-Za-z0-9_~-]+\.html", url):
                raise ValueError("不能添加无法核对来源的岗位链接")
            rid = f"bossLink{n + 1}"
            if rid in used:
                raise ValueError("链接关系标识冲突")
            ET.SubElement(relationships, f"{{{PKG}}}Relationship", {"Id": rid, "Type": REL + "/hyperlink", "Target": url, "TargetMode": "External"})
            ET.SubElement(links, f"{{{MAIN}}}hyperlink", {"ref": f"C{n + 5}", f"{{{REL}}}id": rid})
            total += 1
        # XLSX schema places hyperlinks after data/filters and before page/drawing/table settings.
        after = {"sheetPr", "dimension", "sheetViews", "sheetFormatPr", "cols", "sheetData", "sheetCalcPr", "sheetProtection", "protectedRanges", "scenarios", "autoFilter", "sortState", "dataConsolidate", "customSheetViews", "mergeCells", "phoneticPr", "conditionalFormatting", "dataValidations"}
        index = next((i for i, node in enumerate(sheet) if node.tag.rsplit("}", 1)[-1] not in after), len(sheet))
        sheet.insert(index, links)
        files[filename] = ET.tostring(sheet, encoding="utf-8", xml_declaration=True)
        files[relpath] = ET.tostring(relationships, encoding="utf-8", xml_declaration=True)
    temp = output.with_suffix(".links.tmp")
    try:
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as z:
            for name, content in files.items():
                z.writestr(name, content)
        temp.replace(output)
    finally:
        temp.unlink(missing_ok=True)
    return total
