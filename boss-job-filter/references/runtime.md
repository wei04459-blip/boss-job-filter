# 安装、前置条件与恢复

## 必须满足

- Codex 能执行本机命令、读写文件和访问网络；电脑有可见桌面。无桌面的云端容器不能完成本流程。
- Python 3.10+，优先使用 `load_workspace_dependencies` 返回的 Python。无此工具则使用系统 Python；没有 Python 时使用官方 uv 的用户目录安装与 `uv python install 3.12`，不要假定 python、pip 已存在。
- Chrome 可用，用户可以在专用窗口手动登录 BOSS。Windows 使用原生 Python 与 Chrome，不把 WSL 与 Windows 的本地连接混用。
- GitHub 可下载源码，PyPI 可下载依赖，Chrome 可访问 BOSS。Git 只是获取代码的可选方式，ZIP 也可用。
- 安装目录、虚拟环境和任务输出目录可写；调试端口可用。无需额外模型 API 密钥。

## 安装与启动

仓库根目录的 `install.py` 把 skill 复制到 `~/.agents/skills/boss-job-filter` 并安装依赖。也可指定 `--destination`。目标已存在会停止，不覆盖旧代码、虚拟环境或账号资料。

如果 Codex 已通过 skill-installer 将本仓库的 boss-job-filter 子目录安装到其他位置，沿用该位置，直接运行其中的 `scripts/bootstrap.py`；不要安装两份同名技能。

bootstrap 使用当前 Python 创建 `.venv`，有 uv 则用 uv，无 uv 则用标准 venv/pip，按 requirements.txt 安装。若系统 Python 缺少 venv/ensurepip，用 uv 创建环境或换 Codex 自带 Python。下载中断后，在已复制的 skill 里重跑 bootstrap；失败不能当作安装成功。

成功返回 skill、python 和下一步命令数组。后续使用返回的 Python 或以基础 Python 运行 `scripts/run.py <子命令>`。run.py 自动区分 Windows 的 `.venv/Scripts/python.exe` 与 macOS/Linux 的 `.venv/bin/python`。所有路径按完整参数传递，含空格不拆开。

## 导出运行库

优先使用本机 Codex 的 artifact-tool。若工具返回路径不在默认缓存位置，在已安装 skill 根目录写入 `.runtime.json`：

```json
{
  "node": "/actual/path/from/Codex/node",
  "node_modules": "/actual/path/from/Codex/node_modules"
}
```

Windows 路径使用 JSON 标准转义或正斜杠。也可设置任务环境变量 BOSS_NODE 和 BOSS_NODE_MODULES，二者必须成对。可选 chrome / BOSS_CHROME 指向 Chrome 可执行文件，并非 .app 顶层目录。

配置文件仅属于当前设备，已加入忽略清单。程序从给定运行库解析包，不创建 skill 内 node_modules 软链接，不依赖作者机器路径。显式路径失效时会报错，需重新读取 Codex 路径并更新。

没有 artifact-tool 时，使用安装器准备的 openpyxl，无需 Node/npm/表格插件。数值、日期、全文、筛选表和直接超链接保留；四个汇总公式有保存值并在 Excel 打开后重新计算。此模式不能提供 PNG 预览；用可用 Excel/WPS/LibreOffice 查看四表。没有查看工具时记录视觉检查未完成，不影响已通过的结构与数据校验。

## 环境检查与浏览器

`doctor --output-dir <本次目录>` 返回依赖、系统、可见桌面、Chrome、上游资源完整性、导出引擎、目录写入和本地调试连接。environment_ready 表示静态条件满足；browser_ready 表示本地 CDP 可用，**都不代表 BOSS 已登录**。

`doctor --offline` 不连接浏览器，用于依赖验收。doctor 不向 BOSS 发账号探测请求；BOSS 网络和登录有效性只能通过本人登录和后续真实搜索确认。

执行 setup 打开专用 Chrome。它不复制 cookies、不杀旧浏览器、不重置已有 profile。默认 9222 使用 `~/.boss-zhipin-scraper/chrome-profile`；其他端口各自使用 `~/.boss-job-filter/chrome-<port>`。可用 `--browser-path` 与 `--profile-dir` 覆盖；不要指向日常 Chrome 配置目录。

端口占用或 profile 已在使用时，沿用已核对的端口或选择空闲端口与独立 profile，不结束用户的其他进程。Chrome 未安装时，由 Codex 从 [Chrome 官方页面](https://www.google.com/chrome/) 获取适合系统的版本并安装；系统管理员授权窗口只能由本人处理。Linux 需图形会话，不支持为采集自动切换无头或增加 --no-sandbox。

首次登录或验证码必须由账号本人完成。已有本次登录确认就直接开始搜索；不要反复催问或探测。平台限制后停止，只有用户确认已恢复才能用 `details --resume-confirmed` 续读。

## 执行顺序与恢复

1. `collect --config ... --output ...`：真实页面导航、原生列表响应、逐页存盘；文件已存在不覆盖。最多 10 页/150 条；列表间隔 12 秒。
2. `details --input ...`：读取真实详情正文；每条间隔 3 秒，已完整条目跳过。正文必须来自可见详情且核对岗位 ID，不用全页面文本兜底。
3. `prepare --input ... --output ...`：生成全文复核任务和数据指纹。
4. Codex 阅读每条全文，按 review.md 写 reviews.json。这一步不能用固定通过模板代替。
5. `report --input ... --reviews ... --output ... --preview`：导出并自动验证。verification.verified=true 才是保存内容验收通过；summary.delivery_status 另表示采集与复核是否完成。

列表翻页由文档滚动触发，不能把滚动右侧详情窗当作翻页。重复页、登录要求、限制、超时和异常保留已采集数据并返回原因；列表受阻后不自动开新批次补数。详情恢复只在原文件续读；改变条件后重新生成复核指纹。

| 返回/状态 | 含义与下一步 |
|---|---|
| 退出 0 | 本命令完成；仍需看任务是否部分完成，不能只看退出码交付 |
| doctor 退出 2 | 缺环境条件或浏览器未连接；修复 errors / 执行 setup 后重查 |
| collect/details 退出 2 | 中断或未全部完成；保留文件并说明原因，可导出部分结果 |
| 退出 1 | 输入、依赖、连接或导出等错误；看 error 针对性修复 |
| target_reached | 达到原始岗位上限，继续全文与复核 |
| result_end | 搜索已结束，实际数量可能不足上限 |
| page_limit | 到达页数上限；覆盖不完整，结果保留 |
| login_required / restricted | 需要本人登录或验证，禁止自动绕过或间隔后自行恢复 |
| capture_timeout / browser_error | 当前步骤失败，检查现场；不把未收到响应当作零岗位 |

结构校验包括四表、分类数、原始标识、全文、直接超链接、日期与薪资类型、冻结表头和错误值。交付前做全文抽查和链接抽查；源站登录门槛、链接失效与 Excel 超链接错误分别说明。
