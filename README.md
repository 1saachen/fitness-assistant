# Fitness Assistant

一个完全本地运行的健身管理 MVP，覆盖档案、训练与饮食计划、每日反馈、建议、SQLite 持久化，以及经人工审核后发布的本地知识库。当前应用只开放 `demo` 模式，由确定性的本地规则和本地 RAG 生成结果。

## 本地启动

运行应用需要 Python 3.11+。Node.js 只用于开发和运行完整前端测试，普通本地使用不需要 Node.js。

第一次运行时，在 PowerShell 中进入实际仓库目录并创建虚拟环境：

```powershell
cd <仓库路径>
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn fitness.main:app --host 127.0.0.1 --port 8000
```

已有 `.venv` 时可跳过创建命令。仅运行应用也可以安装 `-e .`；`".[dev]"` 额外安装 pytest 和 ruff，便于执行本文的完整验证。

这是单用户、无认证的本地应用。启动时必须绑定 `127.0.0.1`；不要改绑 `0.0.0.0`，也不要通过端口转发、反向代理等方式暴露到局域网或公网。

浏览器打开 <http://127.0.0.1:8000/>。接口文档位于 <http://127.0.0.1:8000/docs>，健康检查和当前应用状态分别是：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/api/state
```

停止服务时在运行窗口按 `Ctrl+C`。

`demo` 模式不调用外部模型；当前可用模式只有 `demo`，`external model API calls = 0`。档案、计划、反馈和建议写入本地 SQLite，知识检索读取 `data/knowledge/` 中已批准的内容。

## 基本使用流程

1. 在“我的档案”填写目标、身体信息、训练条件、饮食和恢复信息，点击“保存档案”。计划只能基于已保存的档案生成；修改档案后需重新生成旧草案才能确认。
2. 在“本周计划”选择开始日期，点击“生成计划草案”。检查训练、饮食和“方案依据”，再点击“确认这份计划”。每次生成都会留下独立记录。
3. 在“每日反馈”输入当天训练、饮食、睡眠、疲劳或体重等事实，点击“整理为反馈草稿”。核对结构化字段后点击“确认并保存反馈”。
4. 对已确认的反馈点击“生成今日建议”。页面会显示规则建议和“本次调整依据”；若修改已确认反馈，旧建议会被清除，需重新生成。

对应 API 顺序如下：

```text
PUT  /api/profile
POST /api/plans
POST /api/plans/{plan_id}/confirm
POST /api/feedback/parse
POST /api/feedback/{feedback_id}/confirm
POST /api/feedback/{feedback_id}/advice
```

所有生成请求的 `mode` 都应为 `demo`。反馈草稿示例：

```json
{
  "text": "今天完成训练，昨晚睡了5小时，午餐在食堂吃，有点累",
  "date": "2026-09-21",
  "mode": "demo"
}
```

## 两层本地 RAG

本项目将知识使用分为两层，两层都只读取 `review_status: "approved"` 的知识卡，并保存当次使用的快照，避免知识库更新后改变历史记录的含义。

### 1. 计划：baseline 策略模块

全部已批准知识卡被整理为 7 个可审核的 baseline 策略模块。生成计划时会选择并使用与已保存档案目标相适用的全部模块，而不是从知识卡中任取前 5 条。当前减脂档案通常适用全部 7 个模块；生成的策略库保留各模块的行动规则、限制、安全边界和支撑知识 ID，计划记录保存当次使用的模块快照与来源快照。

### 2. 反馈：独立 issue 检索

已确认反馈会先拆成独立 issue，例如睡眠不足、训练疲劳、饮食执行、体重趋势或补剂问题。每个 issue 默认检索 3 张知识卡；当前三张不能覆盖该 issue 的不同子主题时，可扩展到最多 5 张。这个上限按 issue 独立计算，因此一条包含多个 issue 的反馈在合并去重后，总知识卡数可以超过 5。

知识文件缺失或无效时，计划和建议的核心规则流程仍继续运行，保存的 `trace.knowledge_status` 会标记为 `unavailable`。知识库可用但某个 issue 没有匹配项时，该 issue 返回空来源而不阻塞其他 issue；两种情况都不会伪造来源。创作者内容始终保留为“创作者观点/视频观点”，只作为有适用条件的参考，不会自动转化为个体补剂剂量、诊断或医疗结论。

## 查看保存的上下文与轨迹

计划页面会显示“方案依据”，按 baseline 模块展开行动规则、支持知识卡和来源视频。反馈页面会显示“本次调整依据”，按 issue 展开知识卡和来源视频。页面渲染的是生成时保存的快照。

`GET /api/state` 返回当前应用状态，其中 `plans` 和 `feedback` 分别最多包含最近 100 条记录；它不是数据库完整导出或备份接口。计划中的 `strategy_context`、`knowledge_context` 和 `source_ids` 位于 `plans[*].data`，计划轨迹位于 `plans[*].trace`；反馈建议的 `knowledge_context` 和 `source_ids` 位于 `feedback[*].advice`，建议轨迹位于 `feedback[*].trace`。反馈流程不使用 `strategy_context`。

升级前创建的 SQLite 记录可能没有新增的 context 字段，旧 trace 也可能不含当前的知识检索字段。页面会把缺失的 context 按空列表处理并显示为未采用知识库内容；读取 API 时应把缺失的 trace 字段视为未知。不要把旧记录缺少字段误认为数据损坏。

在服务运行时可用 PowerShell 查看最新记录：

```powershell
$state = Invoke-RestMethod http://127.0.0.1:8000/api/state

# 最新计划保存的策略、知识快照、知识 ID 和轨迹
$state.plans[0].data.strategy_context
$state.plans[0].data.knowledge_context
$state.plans[0].data.source_ids
$state.plans[0].trace

# 最新反馈保存的建议知识快照、知识 ID 和轨迹
$state.feedback[0].advice.knowledge_context
$state.feedback[0].advice.source_ids
$state.feedback[0].trace
```

典型计划轨迹包含 `baseline_strategy_selection`、`strategy_ids`、`knowledge_item_ids` 和 `knowledge_status`。典型建议轨迹包含 `issue_extraction`、`knowledge_retrieval`、`issues`、`knowledge_query_terms`、`knowledge_item_ids` 和 `knowledge_status`。

## 知识审核、发布与生成产物

候选知识卡的审核决定保存在本地。启动应用后打开 <http://127.0.0.1:8000/#knowledge>，审核卡片并点击“发布已批准卡片”。发布结果写入 `data/knowledge/{training,fat_loss,supplements,sleep_recovery}/mvp-approved.json` 及其来源文件。

发布知识是 fail-closed 流程。baseline 的策略 membership 是在 `fitness/knowledge_context.py` 中显式审核维护的映射；两条 CLI 只重建和校验产物，不会自动为新批准卡设计策略，也不会替普通审核者决定策略归属。

每次批准集合发生变化后，按以下顺序处理：

1. 运行 `fitness.knowledge_cli` 重建批准 manifest。
2. 人工审核新增或移除的知识 ID，在 `fitness/knowledge_context.py` 更新相应策略 membership；若条目暂不属于任何策略，则必须在相应的审核映射/生成逻辑中明确记录为带原因的 `reference_only`，不能静默遗漏。当前生成器默认 `reference_only` 为空，因此不能仅靠运行 CLI 自动完成这一步。
3. 运行 `fitness.strategy_cli` 重建并验证 baseline 策略库。

批准集合与现有策略库不一致时，计划和反馈知识上下文会立即 fail closed 为 `unavailable`，核心规则仍可运行。不能仅在页面点击“发布已批准卡片”后就视为策略库更新完成。

对应命令如下：

```powershell
cd <仓库路径>
.\.venv\Scripts\python.exe -m fitness.knowledge_cli
# 人工更新并复审 fitness/knowledge_context.py 中的策略 membership/reference_only
.\.venv\Scripts\python.exe -m fitness.strategy_cli
```

第一条命令生成 `data/knowledge/manifest.json`，只收录已批准条目；第二条命令根据已审核的显式映射生成并校验 `data/knowledge/baseline-strategies.json`，要求每个已批准条目被策略覆盖或明确列入 `reference_only`。这两个命令只处理本地结构化数据，不下载视频、不转写音频，也不调用外部模型。

独立关键词检索接口为：

```text
GET /api/knowledge/search?q=睡眠%20镁&limit=5
```

## 项目资料

- [工作日志与路线图](docs/work-log.md)
- [API 合约](docs/api-contract.md)
- [RAG 计划与反馈集成设计](docs/superpowers/specs/2026-09-21-rag-plan-feedback-integration-design.md)
- [人工维护知识库说明](data/knowledge/README.md)
- 本地结构化示例档案：`data/examples/user-profile.json`（默认不纳入 Git）

## 测试与静态检查

在仓库根目录运行完整验证：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/frontend/*.test.cjs
.\.venv\Scripts\ruff.exe check fitness tests
.\.venv\Scripts\python.exe -m compileall -q fitness tests
node --check fitness/static/app.js
git diff --check
```

知识产物的覆盖校验可单独运行：

```powershell
.\.venv\Scripts\python.exe -m fitness.knowledge_cli
.\.venv\Scripts\python.exe -m fitness.strategy_cli
```
