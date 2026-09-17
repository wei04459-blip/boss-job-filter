# BOSS 岗位定向筛选 · Codex Skill

把这个仓库地址交给**能运行本地命令、操作本机 Chrome 的 Codex**，即可按下面的安装指令配置环境，采集 BOSS 直聘岗位、阅读全文、筛选并生成 Excel。

支持城市、岗位关键词、年龄、薪资、经验、学历和企业规模。每任务最多 **150 条去重原始岗位、10 页**；结果不足时保留实际数量。岗位名称后附直达招聘详情的链接。

## 给新设备 Codex 的指令

将下面这段话发送给新设备上的 Codex：

> 请从 https://github.com/wei04459-blip/boss-job-filter 安装 boss-job-filter。先读取 README.md 和 boss-job-filter/SKILL.md，按 README 的新设备安装流程自动准备依赖并运行 doctor。安装成功后继续执行我的岗位筛选任务：确认必要条件，打开专用 Chrome，让我完成首次 BOSS 登录，然后采集列表、逐条读取完整职位描述、完成语义复核、导出并验证 Excel。不要停在安装成功或采集完成；遇到验证码或登录失效时保留进度并告诉我需要的操作。不要使用演示或历史数据补数。

## 前置条件与自动处理范围

| 条件 | 新设备如何准备 |
|---|---|
| 本地 Codex，具备命令执行、文件写入和网络权限 | 使用桌面端，或在有桌面的电脑运行 Codex CLI；只有网页对话、无桌面的云端容器不满足采集条件 |
| Python 3.10+ | 优先调用 Codex 的 `load_workspace_dependencies`，使用返回的 Python 绝对路径；无此工具时按下节安装 |
| Python 依赖 | 安装脚本创建 skill 内独立 `.venv`，自动安装固定版本的 requests、websocket-client、openpyxl |
| Google Chrome 与可见桌面 | 自动查找常见安装位置；未找到则安装官方 Chrome；支持显式指定可执行文件路径 |
| GitHub / PyPI / BOSS 可访问 | GitHub 用于下载代码，PyPI 用于首次安装依赖，BOSS 用于页面访问；网络受限时报告具体失败，不循环重试 |
| BOSS 账号和首次登录 | **账号本人**在专用 Chrome 登录；验证码也由本人完成。安装不能替代登录，也不能保证源站不触发限制 |
| 本机空闲调试端口、可写输出目录 | `doctor` 检查；默认 9222，占用时选另一空闲端口并贯穿本次命令 |
| Excel 导出能力 | 优先用 Codex 提供的 artifact-tool；没有该运行库时自动使用 openpyxl，仍输出完整四表和真实超链接 |
| 全文语义复核 | 当前 Codex 执行，不需要另外的 OpenAI API Key、第三方模型服务、MCP、浏览器扩展或付费采集服务 |
| Excel/WPS/LibreOffice | **生成表格不需要安装**；没有图像渲染运行库时，用可用表格应用做外观检查；无查看工具则明确记录该项未验，不伪称视觉验收 |

### 新设备安装流程（由 Codex 执行）

1. 将仓库克隆或下载解压到一个可写目录。没有 Git 可直接下载 GitHub ZIP；不要把网页 HTML 保存成代码。
2. 找到 Python 3.10+。先用 Codex 返回的运行库路径。若不存在：已有 `uv` 时执行 `uv python install 3.12` 并用 `uv python find 3.12` 获取路径；否则按 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/) 安装到用户目录，再安装 Python。Windows 使用原生 Windows Python 与 Chrome；不要把 WSL 内的 localhost 当成 Windows Chrome 的调试端口。
3. 用上一步的 Python 运行仓库根目录 `install.py`。默认复制至 `~/.agents/skills/boss-job-filter`，自动创建虚拟环境并安装依赖。路径包含空格时作为一个完整参数传递。PowerShell 调用带空格的可执行路径时使用 `&`。
4. 若已通过 Codex 自带 `skill-installer` 安装本仓库中的 `boss-job-filter` 子目录，**不要再复制第二份**，直接运行已安装目录的 `scripts/bootstrap.py`。已有同名技能时先确认其路径；根安装器遇到目标已存在会停止，绝不覆盖旧代码。修复依赖后可重复运行 bootstrap，已满足的依赖会跳过。
5. 阅读安装器 JSON 返回的 `skill`、`python` 和 `next`。后续可用它返回的虚拟环境 Python，或以基础 Python 运行 `scripts/run.py`，后者自动选择 Windows / macOS / Linux 的虚拟环境路径。
6. 若 `load_workspace_dependencies` 提供 artifact-tool，且自动发现不到，将实际 `node` 和 `node_modules` 路径写入已安装 skill 的 `.runtime.json`，格式见 [运行说明](boss-job-filter/references/runtime.md)。不要安装来源不明的同名 npm 包或复制本机的运行库目录。
7. 运行 `doctor --output-dir <本次输出目录>`，修复环境问题，再按 `SKILL.md` 执行 `setup → collect → details → prepare → Codex 逐条复核 → report`。`report` 自动核对保存后的 Excel，生成 `.verification.json`。
8. Codex 通常自动发现新技能；如果选择器里未出现，可直接读取已安装的 `SKILL.md` 继续本次任务，并在之后重启 Codex。当前官方发现规则见 [OpenAI：Build skills](https://learn.chatgpt.com/docs/build-skills)。

本地安装示例（`python3` 仅为示意，实际使用已发现的 Python）：

```sh
python3 install.py
# 自定义目录：
python3 install.py --destination "/your/skill/directory/boss-job-filter"
```

**不要把本仓库作者的求职信息当成新用户条件。** 所有任务配置都由本次请求生成。双模式表示个人求职 / 市场调研；需要实习与全职分别整理时，为两类建立各自明确条件和输出，不能擅自换算日薪或把应届经验等同实习出勤。

## 支持范围与验证

- 面向本机可见 Chrome，代码包含 macOS、Windows、Linux 的路径处理。当前真实浏览器验证来自 macOS；Windows/Linux 的真实登录、权限和 BOSS 页面尚待对应设备验收。
- Python 依赖、空结果/中断/缺失信息、薪资交集、年龄待确认、正文复核指纹、超链接和导出均有自动检查。Windows、macOS、Linux × Python 3.10/3.12 的六组 CI 已通过；真实浏览器登录仍须对应设备验收。
- 新机器上首次登录和平台限制无法承诺无人值守。采集不足 150 条、达到页数上限、详情中断、未复核均明确记录，不冒充完整市场覆盖。
- 安装与导出不依赖作者的缓存、软链接、Chrome 登录态或历史输出。依赖下载失败可在相同安装目录重跑 bootstrap。

详细验收证据见 [新设备迁移验收](docs/portability-validation.md)。

仓库自身代码采用 [MIT 许可证](LICENSE)，随技能安装的许可位于 `boss-job-filter/LICENSE`；上游原作者声明另外原样保留。

## 开发与发布

运行 `python -m unittest discover -s tests -v`。测试的模拟岗位不会混进真实任务。

运行 `python tools/release_check.py` 生成发布文件清单，检查是否漏掉必要资源或混入数据。发布只取该清单；不要把整个工作目录打包上传。当前工作目录的 `outputs/`、浏览器资料、`.venv/`、`node_modules/`、`.runtime.json`、个人配置和原先验收材料都不属于发布包。

基础采集代码来自 [eatmoreduck/boss-zhipin-scraper](https://github.com/eatmoreduck/boss-zhipin-scraper)，固定到已记录提交，保留 MIT 许可。没有依赖未来随时变化的上游主分支。详见 [来源与许可](boss-job-filter/references/upstream.md)。
