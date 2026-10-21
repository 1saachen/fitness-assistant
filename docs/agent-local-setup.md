# 给 Agent 的本地安装与运行指南

这份文档供接收项目的用户及其 Agent 使用。目标是在接收者自己的电脑上安装、配置、启动并验证循序（Xunxu）。请将本文和完整项目源码一起交付；只有本文、Python 安装包或 `fitness/` 目录不够。

## 1. Agent 的执行约定

收到“请按本文在我的电脑上运行项目”后，请执行下面的流程，并根据实际操作系统调整命令。

1. 找到接收者的项目根目录，检查源码、数据文件、Python 版本和现有配置。
2. 在项目内建立虚拟环境，安装依赖，先以 `demo` 模式验证本地运行。
3. 用户要求在线模型时，再配置接收者自己的供应商、模型和密钥，验证 `live`。
4. 启动服务，检查页面、静态资源、健康接口、状态接口和知识库；向用户报告真实验证结果及访问地址。

执行时遵循以下规则：

- 本文中的路径是示例。使用接收者的实际路径，不要照搬项目作者电脑上的盘符、用户名或虚拟环境。
- 保留现有配置和数据。存在 `.env` 时先检查非敏感配置，不要直接覆盖；存在数据库时不要执行重置、删除、演示初始化或恢复覆盖。
- 不输出密钥，不将 `.env` 或数据库加入版本控制。需要密钥时，请用户在本地填写或使用其已有的环境变量。
- 安装依赖通常需要联网。调用在线模型还会将相关档案、反馈和检索上下文发送到配置的供应商，并可能产生费用；先确认用户确实需要在线模式。
- 本项目是单用户、无登录认证的本地应用，服务绑定 `127.0.0.1`。不要为了访问方便改为 `0.0.0.0` 或公开代理。
- 可按本地权限正常执行环境检查、虚拟环境创建、依赖安装和隔离验证；涉及删除用户数据、覆盖恢复、系统级安装等操作时，遵循用户授权及本地 Agent 的权限规则。
- 不要因运行问题自动重写业务代码、重新审核/发布知识卡或换用其他模型供应商。先定位环境、路径、配置和网络原因。
- 区分“服务可用”“demo 流程可用”和“在线模型实际生成成功”。没有实际在线调用，不能宣称在线功能已通过。

## 2. 项目组成与环境要求

| 项目 | 要求或说明 |
| --- | --- |
| Python | 3.11 或以上；新环境建议先用 3.11/3.12，与 `pyproject.toml` 的要求核对 |
| 后端 | FastAPI + Uvicorn，由 pip 自动安装 |
| 前端 | 仓库内 HTML/CSS/JavaScript，由后端提供；无需 npm 安装或前端构建 |
| 数据库 | 本地 SQLite，由 Python 自带支持；应用自动建库和迁移，无需安装数据库服务 |
| 知识库 | 仓库内 JSON 文件；无需向量数据库、下载视频或重新采集资料 |
| 浏览器 | 可访问本机 HTTP 服务的现代浏览器 |
| Node.js | 普通使用不需要；运行前端开发测试时才需要 |
| Git | clone 时需要；接收完整源码压缩包后运行不需要 |
| Docker | 当前没有提供 Dockerfile 或 Compose；按本文直接运行 |

在项目根目录执行所有后续命令。确认至少有：

```text
pyproject.toml
.env.example
fitness/                         # 完整 Python 源码
fitness/static/                  # 前端页面与资源
data/examples/demo-profile.json  # 合成演示档案
data/knowledge/baseline-strategies.json
data/knowledge/sources/          # 来源 JSON
data/knowledge/training/         # 已发布知识卡
data/knowledge/fat_loss/
data/knowledge/supplements/
data/knowledge/sleep_recovery/
data/ingest/bilibili-20260916/mvp-final-card-candidates.json
data/ingest/bilibili-20260916/nutrition-era-catalog.json
```

还应保留 `data/evaluation/`（知识验证使用）、`tests/` 和 `docs/`。知识审核候选文件用于审核页面，普通计划主要读取已发布知识及 baseline 策略。

交付源码时包含当前要交付版本的全部文件。若作者本地仍有未提交的新模块，Git clone 不会自动包含它们，应先将准备交付的源码纳入交付版本。不要把作者的 `.env`、`.venv/`、`data/local/`、真实个人档案、Cookie、日志或私人备份一起打包。`data/local/` 不存在是正常的，会按需创建。

项目目前使用依赖版本范围，没有依赖锁文件；安装时解析出的具体版本可能不同。不要把“可按步骤安装”理解为所有平台的依赖版本完全一致。

## 3. Windows / PowerShell 安装

进入实际解压或 clone 后的目录：

```powershell
Set-Location 'C:\path\to\xunxu'
py -0p
py -3.11 --version
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

若安装的是 Python 3.12，可把创建命令改为 `py -3.12 -m venv .venv`；没有 `py` 启动器时，先确认 `python --version`，再用满足要求的 `python -m venv .venv`。不要只为匹配命令而卸载已有 Python。

已有 `.venv` 时，先用 `.\.venv\Scripts\python.exe --version` 检查它是否可用且版本满足要求。不要复用从别的电脑拷来的虚拟环境；需要重建时先确认该目录仅是可重建的虚拟环境。

本文直接调用虚拟环境内的解释器，无需执行 `Activate.ps1`，因此不需要修改 PowerShell 执行策略。

仅在 `.env` 不存在时复制模板：

```powershell
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
```

## 4. macOS / Linux 安装

```bash
cd '/path/to/xunxu'
python3 --version
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
if [ ! -e .env ]; then cp .env.example .env; fi
```

确认 `python3` 为 3.11+；如果默认版本较旧，改用本机已有的 `python3.11` 或 `python3.12` 建立环境。部分 Linux 发行版需要额外安装与解释器匹配的 `python3-venv`；按实际发行版处理，不要混用系统 pip 和虚拟环境 pip。后续 Windows 命令中的 `.\.venv\Scripts\python.exe`，在 macOS/Linux 替换为 `./.venv/bin/python`。

## 5. 首次配置：先验证 demo

新环境使用 `.env.example` 的默认配置即可，确认：

```dotenv
FITNESS_LIVE_ENABLED=false
FITNESS_TIMEZONE=Asia/Shanghai
FITNESS_DB_PATH=data/local/fitness.sqlite3
```

`demo` 不调用外部模型，不需要密钥；首次安装 Python 依赖仍可能联网。时区使用 IANA 名称，如 `Asia/Shanghai`、`Europe/London`，应根据接收者实际所在地调整，影响“今天”的日期。

应用读取项目根目录的 `.env`，**进程已有环境变量优先于 `.env`**。配置改后需重启服务。`FITNESS_DB_PATH` 若为相对路径，按启动命令的当前工作目录解析，所以始终从项目根目录启动；使用自定义位置时建议填写有写入权限的绝对路径。

不要直接打印 `.env` 或完整环境变量来诊断问题，检查开关、时区、路径、模型和端点等非敏感项即可。

## 6. 启动与验收

Windows：

```powershell
.\.venv\Scripts\python.exe -m uvicorn fitness.main:app --host 127.0.0.1 --port 8000
```

macOS/Linux：

```bash
./.venv/bin/python -m uvicorn fitness.main:app --host 127.0.0.1 --port 8000
```

该命令持续运行是正常现象。使用另一终端进行检查。Agent 如需后台启动，应使用其环境支持的进程管理方式，记录 PID、日志位置和停止方式，不要让服务随一次短命令结束而退出。

| 地址 | 验收标准 |
| --- | --- |
| `http://127.0.0.1:8000/health` | HTTP 200，JSON 为 `{"ok": true}` |
| `http://127.0.0.1:8000/api/state` | HTTP 200，新 demo 环境应有 `mode: "demo"`；空库 `profile: null` 正常 |
| `http://127.0.0.1:8000/` | 页面正常显示，可进入“我的档案”等界面 |
| `http://127.0.0.1:8000/static/app.js` | HTTP 200，返回 JavaScript |
| `http://127.0.0.1:8000/docs` | 可查看自动生成的接口文档 |

Windows 可用：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
$state = Invoke-RestMethod http://127.0.0.1:8000/api/state
$state | Select-Object mode, available_modes, profile_version, knowledge_status, today
```

macOS/Linux 可用 `curl -fsS http://127.0.0.1:8000/health`。状态接口可能包含个人资料，报告时只输出必要的非敏感字段。

空库没有档案时 `knowledge_status: "unknown"` 不代表知识损坏。可独立检查已审核知识：

```powershell
.\.venv\Scripts\python.exe -m fitness.knowledge_cli
```

预期输出 `indexed N approved knowledge items`，`N` 应大于 0；它会生成可重建的 `data/knowledge/manifest.json`。退出成功但数量为 0 也不应当作完整知识功能验收通过，应检查交付文件。不要为消除错误而自动批准候选卡。

### 首次使用真实档案

让接收者在页面填写自己的档案并保存，生成长期计划草案，核对后确认启用，再生成当天计划并记录每日反馈。确认档案、计划等操作应由用户决定；Agent 不应把演示资料冒充接收者信息。

### 可选：隔离数据库演示

想验证“档案 → 计划 → 反馈 → 建议”的本地闭环，可用一个**尚不存在的专用演示数据库路径**：

```powershell
.\.venv\Scripts\python.exe -m fitness.demo_cli walkthrough --db-path data/local/setup-demo.sqlite3
```

这使用合成演示档案，不修改默认业务数据库，不调用外部模型。若该路径已有演示记录，另选一个新文件名，不要为了验证而删除旧库。命令应退出成功并返回各记录 ID 与知识状态；它验证的是兼容周计划闭环，新长期/当天流程还需在页面验收。

如用户明确想在页面试用合成档案，且默认库尚无档案，可执行 `python -m fitness.demo_cli init`（使用虚拟环境解释器）。它不会覆盖已有档案；正式使用前应让用户了解当前是演示身份。普通安装无需执行任何 `reset` 命令。

## 7. 可选：配置在线模型

用户明确需要真实模型时，在其本地 `.env` 中填写自己的配置。默认适配 DeepSeek 的 OpenAI 兼容 Chat Completions 接口：

```dotenv
FITNESS_LIVE_ENABLED=true
FITNESS_API_KEY=在本地填写接收者自己的密钥
FITNESS_BASE_URL=https://api.deepseek.com
FITNESS_MODEL=deepseek-chat
FITNESS_TIMEOUT_SECONDS=60
FITNESS_AGENT_MAX_CALLS=12
FITNESS_AGENT_MAX_TOOLS=20
FITNESS_AGENT_MAX_REVISIONS=2
FITNESS_AGENT_TIMEOUT_SECONDS=180
FITNESS_AGENT_MAX_OUTPUT_TOKENS=4096
```

密钥示例是占位符，不能直接使用。其他兼容供应商必须同时匹配它自己的密钥、模型名称和 API 基础地址。程序在基础地址后追加 `/chat/completions`，不要把完整接口路径填入 `FITNESS_BASE_URL`；如果供应商要求 `/v1`，则保留基础地址中的 `/v1`。远程地址要求 HTTPS。是否真正兼容工具调用和结构化候选输出，需通过实际生成验证。

`DEEPSEEK_API_KEY` 仅在明确的默认 DeepSeek 基础地址下作为备用读取；跨供应商配置统一使用 `FITNESS_API_KEY`。不要把作者的密钥交给接收者。

重启后检查 `/api/state` 的 `mode: "live"` 和 `available_modes`，再在用户允许真实调用的前提下生成一次计划，检查页面训练/饮食来源和错误提示。页面显示 live 只证明开关和非空密钥满足条件，不能证明鉴权、余额、网络或生成能力正常。

新长期/当天 live 训练或饮食生成失败时，会保留旧计划并返回错误或待补信息，不自动存入 demo 替代方案。部分旧周计划/反馈/建议接口仍可能回退到本地结果，因此不能仅以“有建议文字”判断模型成功。

## 8. 停止、再次启动、更新与备份

- 前台运行时按 `Ctrl+C` 停止。下次使用进入同一目录，用同一虚拟环境重复启动命令即可，数据库保留在原路径。
- 更新项目之前，用项目提供的备份命令保存数据库，尤其是首次运行新版本之前。迁移在打开数据库时自动发生，程序拒绝高于其支持版本的数据库；不要手工降低 schema 版本或删表。
- 停止旧服务后更新源码，重新执行 `python -m pip install -e .`，然后启动并重复健康检查。虚拟环境不能跨电脑迁移。

Windows 备份示例（目标文件必须尚不存在，使用实际数据库路径）：

```powershell
.\.venv\Scripts\python.exe -m fitness.data_cli backup --database data/local/fitness.sqlite3 --destination data/local/before-update.sqlite3
```

不要在运行中仅复制 SQLite 主文件作为完整备份，提交数据可能还在 WAL 中；项目命令使用 SQLite 备份 API。备份含个人信息，仅保存在用户选择的位置。恢复使用 `restore-preview` 和 `restore-confirm` 的指纹确认流程，详见 [数据边界](data-boundaries.md)，不要在安装流程中自动恢复或覆盖。

## 9. 常见问题定位

| 现象 | 检查与处理 |
| --- | --- |
| 找不到 Python、版本低于 3.11 | 检查本机解释器路径和版本；按用户授权安装合适版本后重建环境 |
| `No module named fitness` / `uvicorn` | 确认处于项目根目录，用同一个虚拟环境解释器执行安装与启动；重新执行 `-m pip install -e .` |
| pip 安装失败 | 检查完整错误、网络、代理和 Python 版本；不要通过关闭 TLS 校验解决 |
| PowerShell 禁止脚本执行 | 直接调用 `.venv\Scripts\python.exe`，无需激活脚本 |
| 8000 端口被占用 | 检查是否已有本项目服务；不终止未知进程。可改为 `--port 8001` 并相应更新所有访问地址 |
| SQLite 无法打开 / 权限错误 | 检查工作目录、`FITNESS_DB_PATH`、父目录写入权限和只读路径；不要将数据库放在不可写的安装目录 |
| `database is locked` | 检查重复服务或维护命令是否同时使用该库；停止自己启动的多余进程后重试 |
| 日期不对 / 时区异常 | 检查 `FITNESS_TIMEZONE` 是否是有效 IANA 名称，依赖是否已完整安装，重启后核对 `today` |
| 改 `.env` 无效 | 检查是否重启、是否另有旧进程，以及进程环境变量是否覆盖该值；不要输出密钥 |
| 知识不可用、数量为 0 | 检查 `data/knowledge/`、来源 JSON、baseline 策略是否齐全；不要只交付 wheel 或 `fitness/` |
| live 未出现 | 同时检查开关、非空密钥与重启；此步骤不需要暴露密钥内容 |
| live 超时或调用失败 | 检查端点、模型、工具调用兼容性、鉴权、余额、代理及日志中的安全原因码；不要直接无限增大预算 |
| 新计划不能确认 / 冲突 | 刷新并基于当前已保存档案重新生成；不要绕过版本检查或直接改数据库 |

## 10. 开发检查与 Agent 交付报告

普通用户使用无需运行全套开发检查。需要开发验证时：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check fitness tests
node --test tests/frontend/*.test.cjs
```

前端测试需可用的 Node.js；如果当前 shell 不展开通配符且 Node 不接受该路径，由 Agent 枚举 `tests/frontend/` 下的 `.test.cjs` 文件后传给 `node --test`。测试期间不要启用真实模型调用。

完成后，Agent 应向接收者报告：

1. 项目实际位置、操作系统、Python 版本和虚拟环境路径。
2. 实际访问地址、启动命令、服务是否仍在运行及停止方式。
3. 当前 demo/live 模式、数据库位置和时区，不包含密钥或个人资料。
4. 健康接口、状态接口、页面/静态资源、知识索引的实际结果。
5. 做过的流程验证，以及未验证内容；在线生成未调用时明确写“未验证”。
6. 仍需用户完成的事项，如填写真实档案、配置密钥或确认计划。

可直接复制给接收者 Agent 的任务：

> 请阅读项目中的 `docs/agent-local-setup.md`，按照实际系统在我的电脑上完成环境检查、安装、demo 启动与验收。保留已有配置和个人数据，不执行重置，不输出密钥。完成后给我访问地址、再次启动/停止方法和真实检查结果。如果我没有明确要求在线模型，先使用 demo；需要我补充的信息请准确指出。
