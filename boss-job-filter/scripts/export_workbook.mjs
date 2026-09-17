#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
// Resolve from the runtime returned by Codex, without symlinks or local packages.
const resolveRuntime = createRequire(path.join(process.env.BOSS_NODE_MODULES, "../boss-resolver.cjs"));
const { Workbook, SpreadsheetFile } = await import(pathToFileURL(resolveRuntime.resolve("@oai/artifact-tool")).href);

const [input, output, ...flags] = process.argv.slice(2);
if (!input || !output) throw new Error("Usage: export_workbook.mjs report.json output.xlsx [--preview]");
const data = JSON.parse(await fs.readFile(input, "utf8"));
const wb = Workbook.create();
const names = ["符合岗位", "待确认岗位", "原始岗位与判定", "任务说明"];
const sheets = names.map(name => wb.worksheets.add(name));
const palette = { navy: "#173B4A", teal: "#117C78", amber: "#A66B17", pale: "#F2F7F8", ink: "#203E49", muted: "#60747D" };
const fields = { city: "城市", salary: "薪资", degree: "学历", experience: "经验", scale: "企业规模", age: "年龄", detail: "详情", role: "岗位方向" };
const col = n => { let s = ""; for (n++; n; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + (n - 1) % 26) + s; return s; };
const literal = value => {
  if (value == null) return "";
  if (Array.isArray(value)) return value.join("；");
  if (typeof value !== "string") return value;
  if (value.length > 32767) throw new Error("单元格超过 Excel 上限；请保留外部原文并调整导出，不能静默截断");
  return /^[=+@-]/.test(value) ? "'" + value : value;
};
// Preserve the displayed local wall time; the source ISO timestamp remains in raw JSON.
const date = s => s ? new Date(s.slice(0, 19) + "Z") : "";
const compact = x => x == null ? "不筛选" : Array.isArray(x) ? (x.join("、") || "不筛选") : typeof x === "object" ? JSON.stringify(x) : String(x);
const headers = ["序号", "岗位名称", "岗位链接", "公司名称", "薪资原文", "学历要求", "经验要求", "企业规模", "最终结论", "判定依据 / 待确认事项", "城市 / 区域", "岗位职责摘要", "年龄要求原文", "计薪单位", "薪资下限（元）", "薪资上限（元）", "年发薪月数", "招聘者活跃状态", "行业", "福利原文", "搜索关键词", "列表采集时间", "详情采集时间", "岗位标识"];
const baseRow = (j, n) => [n + 1, j.title, j.url, j.company, j.salary, j.degree, j.experience, j.scale, j.status, j.reason, [j.city, j.area].filter(Boolean).join(" / "), j.jd_summary, j.checks.age.evidence || (data.config.age == null ? "未启用年龄条件" : "未写明确年龄要求"), j.salary_parsed.unit || "未明确", j.salary_parsed.min, j.salary_parsed.max, j.salary_parsed.months, j.active_status || "未获取到", j.industry, j.welfare, j.source_keyword, date(j.collected_at), date(j.detail_collected_at), j.job_id];
const auditHeaders = [...headers, ...Object.values(fields).flatMap(label => [label + "判定", label + "理由", label + "证据"]), "详情读取状态", "详情失败原因", "完整职位描述", "原始岗位 URL", "实习出勤原文"];

function title(sheet, titleText, subtitle, lastCol) {
  sheet.showGridLines = false;
  sheet.tabColor = sheet.name === "待确认岗位" ? palette.amber : palette.teal;
  const full = sheet.getRange(`A1:${lastCol}4`);
  full.format.font = { name: "PingFang SC", size: 11, color: palette.ink };
  sheet.mergeCells("A1:H1");
  sheet.getRange("A1").values = [[titleText]];
  sheet.getRange("A1:H1").format = { font: { name: "PingFang SC", size: 20, bold: true, color: palette.navy }, rowHeight: 38 };
  sheet.mergeCells("A2:H2");
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange("A2:H2").format = { font: { size: 10, color: palette.muted }, rowHeight: 34, wrapText: true };
  sheet.getRange(`A4:${lastCol}4`).format = { fill: palette.navy, font: { bold: true, color: "#FFFFFF" }, rowHeight: 32, wrapText: true };
  sheet.freezePanes.freezeRows(4);
}

function writeJobs(sheet, jobs, audit = false) {
  const hs = audit ? auditHeaders : headers;
  const last = col(hs.length - 1);
  const scope = `${data.config.mode} · ${data.config.city} · ${data.config.keywords.join(" / ")} ｜ 本表 ${jobs.length} 条 · 全部样本 ${data.summary.total} 条`;
  title(sheet, `BOSS 岗位筛选 / ${sheet.name}`, scope, last);
  sheet.getRange(`A4:${last}4`).values = [hs];
  if (jobs.length) {
    const rows = jobs.map((j, n) => {
      const row = baseRow(j, n);
      if (audit) row.push(...Object.keys(fields).flatMap(k => [j.checks[k].status, j.checks[k].reason, j.checks[k].evidence]), j.detail_status, j.detail_error, j.jd, j.url, j.detail_fields?.internship_schedule);
      return row.map(literal);
    });
    sheet.getRange(`A5:${last}${jobs.length + 4}`).values = rows;
    const table = sheet.tables.add(`A4:${last}${jobs.length + 4}`, true, audit ? "AllJobRecords" : sheet.name === "符合岗位" ? "QualifiedJobs" : "PendingJobs");
    table.showFilterButton = true;
    sheet.getRange(`A5:${last}${jobs.length + 4}`).format.fill = "#FFFFFF";
    for (let n = 0; n < jobs.length; n++) {
      const r = n + 5;
      const url = jobs[n].url;
      if (!/^https:\/\/www\.zhipin\.com\/job_detail\/[A-Za-z0-9_~-]+\.html$/.test(url)) throw new Error("岗位来源链接格式不正确");
      // HYPERLINK returns an unsupported-operation string in this runtime.
      // The Python exporter adds standard XLSX hyperlink relationships after export.
      sheet.getRange(`C${r}`).values = [["打开岗位"]];
      sheet.getRange(`C${r}`).format.font = { color: "#146D96" };
      if (n % 2 === 1) sheet.getRange(`A${r}:${last}${r}`).format.fill = palette.pale;
      sheet.getRange(`I${r}`).format = { font: { bold: true, color: jobs[n].status === "符合" ? palette.teal : jobs[n].status === "待确认" ? palette.amber : "#9A4B4B" } };
    }
    sheet.getRange(`A5:${last}${jobs.length + 4}`).format = { font: { name: "PingFang SC", size: 10 }, wrapText: true, verticalAlignment: "center", rowHeight: 50 };
    sheet.getRange(`O5:Q${jobs.length + 4}`).setNumberFormat("#,##0.##");
    sheet.getRange(`V5:W${jobs.length + 4}`).setNumberFormat("yyyy-mm-dd hh:mm");
  } else {
    sheet.mergeCells("A5:H6");
    sheet.getRange("A5").values = [["本次没有此类岗位。请查看“任务说明”区分筛选结果与采集状态。"]];
    sheet.getRange("A5:H6").format = { wrapText: true, font: { color: palette.muted }, rowHeight: 30 };
  }
  const widths = [7, 34, 13, 26, 19, 14, 15, 19, 12, 60, 24, 62, 48, 12, 18, 18, 14, 20, 22, 40, 20, 24, 24, 44];
  hs.forEach((_, n) => sheet.getRange(`${col(n)}1:${col(n)}${jobs.length + 6}`).format.columnWidth = widths[n] || (n >= headers.length && (n - headers.length) % 3 === 0 ? 13 : 52));
  // Reapply header styling after table creation.
  sheet.getRange(`A4:${last}4`).format = { fill: palette.navy, font: { bold: true, color: "#FFFFFF" }, rowHeight: 36, wrapText: true };
}

writeJobs(sheets[0], data.jobs.filter(j => j.status === "符合"));
writeJobs(sheets[1], data.jobs.filter(j => j.status === "待确认"));
writeJobs(sheets[2], data.jobs, true);
const meta = sheets[3];
meta.showGridLines = false;
meta.tabColor = palette.navy;
meta.mergeCells("A1:B1");
meta.getRange("A1").values = [["BOSS 岗位筛选 / 任务说明"]];
meta.getRange("A1:B1").format = { font: { name: "PingFang SC", size: 20, bold: true, color: palette.navy }, rowHeight: 42 };
const c = data.collection, s = data.summary;
const statusNames = { target_reached: "达到本次原始样本上限", result_end: "平台明确返回搜索结束", page_limit: "达到页数上限，覆盖未完成", restricted: "平台要求验证，已停止", login_required: "需要人工登录", capture_timeout: "未收到后续页面，保留部分结果", interrupted: "人工中断", browser_error: "浏览器连接或页面异常", partial: "部分完成", complete: "完成", not_started: "尚未开始", running: "执行中" };
const rows = [
  ["项目", "内容"],
  ["交付状态", s.delivery_status],
  ["模式", data.config.mode],
  ["城市", data.config.city],
  ["岗位关键词", data.config.keywords.join("、")],
  ["原始岗位上限", data.config.limit],
  ["实际去重岗位", s.total],
  ["符合岗位", null], ["待确认岗位", null], ["排除岗位", null], ["分类合计", null],
  ["采集状态", statusNames[c.status] || c.status],
  ["详情已读取 / 未完整读取", `${s.detail_complete} / ${s.detail_incomplete}`],
  ["详情采集状态", statusNames[c.detail_status] || c.detail_status],
  ["已复核 / 尚未复核 / 方向待确认", `${s.reviewed} / ${s.review_outstanding} / ${s.role_pending}`],
  ["求职者年龄", compact(data.config.age)],
  ["薪资条件（元）", compact(data.config.salary)],
  ["学历档位", compact(data.config.degree)],
  ["经验档位", compact(data.config.experience)],
  ["企业规模档位", compact(data.config.scale)],
  ["薪资口径", "岗位薪资区间与用户区间有交集；并不表示企业承诺支付区间中的某一金额。"],
  ["计薪单位", "月、天、小时、年分别比较；不自行换算。年发薪月数单列，不折算月薪。"],
  ["严格档位", "学历、经验、规模只接受指定档位。明确不限与字段缺失分开处理。"],
  ["年龄口径", "启用后只看明确任职年龄要求；未写、含糊、冲突均待确认。不从团队年龄推断。"],
  ["结论口径", "任一条件明确不符即排除；无明确不符但有未知则待确认；全部已验证通过才符合。"],
  ["详情与复核", "职位方向需逐条阅读职责；正文与列表冲突按待确认处理。读取失败不会计入符合。"],
  ["样本边界", s.coverage],
  ["获取页数 / 去除重复 / 无效记录", `${c.pages_received || 0} / ${c.duplicates || 0} / ${c.invalid_rows || 0}`],
  ["搜索开始时间", c.started_at || "未记录"],
  ["列表结束时间", c.finished_at || "未记录"],
  ["详情结束时间", c.details_finished_at || "未记录"],
  ["时间口径", "表内时间沿用采集机器当地时间；上述 ISO 时间带有时区。"],
  ["异常记录", (c.issues || []).join("；") || "无"],
  ["未执行的关键词", data.config.keywords.filter(k => !(c.queries || []).some(q => q.keyword === k)).join("、") || "无"],
  ["筛选前置说明", c.salary_prefilter || "无"],
  ["表格使用", "岗位名称后紧接“打开岗位”链接，可直达具体招聘页面。冻结前四行；结果表可在表头筛选。完整 JD 和逐项证据在“原始岗位与判定”右侧。"],
  ["结果含义", data.config.mode === "个人求职" ? "符合仅指本次指定条件通过，不等于全部任职资格或录用保证。" : "样本仅供本次定向调研，不能外推为全城市招聘市场。"],
  ["采集基础", "eatmoreduck/boss-zhipin-scraper · MIT · eb5a8e646d4e4bfc024cf53f2a5b543ad8d75edc"],
  ...((c.queries || []).flatMap(q => [[`搜索：${q.keyword}`, `${q.pages} 页；${statusNames[q.status] || q.status}`], ["搜索来源 URL", q.url]])),
];
meta.getRange(`A3:B${rows.length + 2}`).values = rows.map(r => r.map(literal));
meta.getRange(`A3:B${rows.length + 2}`).format = { font: { name: "PingFang SC", size: 11, color: palette.ink }, wrapText: true, verticalAlignment: "center", rowHeight: 42 };
meta.getRange("A3:B3").format = { fill: palette.navy, font: { color: "#FFFFFF", bold: true }, rowHeight: 30 };
meta.getRange(`A4:A${rows.length + 2}`).format.fill = palette.pale;
meta.getRange("A1:A50").format.columnWidth = 34;
meta.getRange("B1:B50").format.columnWidth = 112;
meta.getRange("B8:B13").format.horizontalAlignment = "left";
meta.freezePanes.freezeRows(3);
const last = Math.max(5, data.jobs.length + 4);
for (const [row, status] of [[10, "符合"], [11, "待确认"], [12, "排除"]]) meta.getRange(`B${row}`).formulas = [[`=COUNTIF('原始岗位与判定'!$I$5:$I$${last},"${status}")`]];
meta.getRange("B13").formulas = [["=SUM(B10:B12)"]];
for (const [row, expected] of [[10, s.counts["符合"]], [11, s.counts["待确认"]], [12, s.counts["排除"]], [13, s.total]]) {
  const actual = meta.getRange(`B${row}`).values[0][0];
  if (actual !== expected) throw new Error(`分类数量校验失败 B${row}: ${actual} != ${expected}`);
}
const dir = path.dirname(path.resolve(output));
await fs.mkdir(dir, { recursive: true });
const checks = [];
for (const sheet of sheets) checks.push(await wb.inspect({ kind: "table,region", sheetId: sheet.name, range: sheet.name === "任务说明" ? "A3:B16" : "A4:H9", maxChars: 3500, tableMaxRows: 5, tableMaxCols: 8 }));
checks.push(await wb.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#N/A|#NAME\\?|#NUM!|#SPILL!", options: { useRegex: true, maxResults: 30 }, maxChars: 3000 }));
await fs.writeFile(output.replace(/\.xlsx$/i, ".inspection.json"), JSON.stringify(checks, null, 2));
const file = await SpreadsheetFile.exportXlsx(wb);
await file.save(output);
if (flags.includes("--preview")) {
  for (const sheet of sheets) {
    const preview = await wb.render({ sheetName: sheet.name, range: sheet.name === "任务说明" ? "A1:B16" : "A1:I10", scale: 1.4, format: "png" });
    await fs.writeFile(path.join(dir, `preview-${sheet.name}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
  const preview = await wb.render({ sheetName: "原始岗位与判定", range: "I4:M8", scale: 1, format: "png" });
  await fs.writeFile(path.join(dir, "preview-判定依据.png"), new Uint8Array(await preview.arrayBuffer()));
}
console.log(JSON.stringify({ output, sheets: names, rows: data.jobs.length, verifiedCounts: s.counts }));
