# 上游与本次复用

- 项目：https://github.com/eatmoreduck/boss-zhipin-scraper
- 固定版本：`eb5a8e646d4e4bfc024cf53f2a5b543ad8d75edc`
- 许可证：MIT，完整文本随附 `scripts/vendor/boss_zhipin_scraper/LICENSE`。
- 原样收录：`scripts/boss_cdp_raw.py`、`data/city_codes.json` 及 LICENSE。

封装复用 CDP 连接、专用 Chrome 启动、城市及筛选映射、原生列表响应捕获、基础岗位映射和职位描述清洗。上游完整脚本包含本技能未使用的其他功能；执行入口始终为 `scripts/boss_jobs.py`，不调用上游直接接口采集或整个默认工作流。

本地新增独立字段、保守规则引擎、逐条正文复核、任务状态和中文工作簿。兼容修正位于 `browser.py`，没有修改 vendored 源文件：前台标签、按 CDP session 隔离事件、逐页响应错误检查、只检查职位描述的截断情况、实习出勤与经验分开。

许可证来源：https://github.com/eatmoreduck/boss-zhipin-scraper/blob/eb5a8e646d4e4bfc024cf53f2a5b543ad8d75edc/LICENSE

截至 2026-09-15，本机 Chrome 152 已验证深圳“AI运营”两页 30 条及全部详情；10 页和 150 条的上限、重复页、后续页受限等用自动化模拟测试验证。不能把此验证解释为任意城市或未来浏览器版本永久可用。

2026-09-17 迁移检查补充：安装不再依赖作者虚拟环境和软链接；Chrome 启动由 runtime.py 管理，不终止已有浏览器；城市解析只用随附城市表，未知城市报错，不激活上游在线城市接口兜底。新连接初始化上游延迟依赖，保留其事件读取能力。用隔离安装完成 3 条新采集岗位的列表、全文、复核及两种 Excel 导出验证。
