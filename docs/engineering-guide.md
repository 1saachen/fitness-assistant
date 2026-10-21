# 循序 · 工程文档

一个由用户自备模型 API 驱动的健身管理应用，以“长期计划 + 当天计划”为主流程。训练与饮食均由模型设计，程序提供校验、运行预算和可靠状态管理。训练模型可以直接提出本地目录之外的动作，填写名称、器械、组次、重量、RPE和说明；程序为没有标识的新动作生成稳定ID，供后续反馈匹配，动作库仅作为可选参考。饮食模型根据档案、预算、偏好、可用食物、已吃内容及训练安排设计餐单，本地热量计算仅为起始参考。

任何生成失败或需要补信息时，保留旧计划并明确返回问题或错误，不保存本地规则替代方案。已完成训练、已吃餐次、限制解除和循环推进由程序根据确认事实管理；每日餐单不得自动修改已确认长期营养目标。新的自由动作只能根据明确声明的器械及已有目录信息检查器械约束，不代表已完成动作语义或适用性审查；同名动作可关联历史，不同名称不会自动判定为同一动作。

设计与实施记录见 [harness 设计](superpowers/specs/2026-10-20-model-led-agent-harness-design.md) 和 [第一阶段计划](superpowers/plans/2026-10-20-model-led-training-agent.md)。

在线每日反馈支持自然语言复盘：先保存原文，再由模型结合近期原文、个人记忆、当前计划与按需检索的历史/专业知识回应。默认是训练结束或睡前的“日终复盘”，不会改写当天；模型可维持、追问、给建议、自动调整未来某日，或创建待确认的长期草稿。只有明确选择“调整今天剩余部分”时，才允许调整今天尚未完成的内容。查看已有当天计划只读取，不因新反馈自动重排。

档案的“力量参考”可选填深蹲、卧推、硬拉单次最大重量或估算1RM，以及严格自重引体最大连续次数、成绩日期和备注；未知留空，引体暂时做不了可填0，不要求专门测试极限。力量起点、计划建议与实际表现分别保留：日常可反馈“卧推45kg，8/8/7次，末组RPE9”，模型参考近期同动作的实际表现校准后续安排，不把计划重量当成成绩，不自动改档案1RM。反馈页集中于记录和模型回应，暂不展示近期趋势卡。

个人记忆按事实、偏好、限制、待确认问题和模型归纳分开，带反馈ID及修订引用。更正优先；过敏和未解除限制不自行过期。接近上下文预算时由模型压缩，保留保护条目及来源，原始记录和历史快照不删除。失败保留原文、旧记忆和计划，页面区分理解失败、记忆整理失败与计划调整失败，并允许重试。模型归纳仍可能有误，可在后续反馈中直接更正。全库恢复备份包含记忆快照与反馈回应；旧反馈导出格式仍以原文和事实为主，不承载整个记忆库。

## 本地启动

**交给其他人或其 Agent 使用：**请先阅读 [给 Agent 的本地安装与运行指南](agent-local-setup.md)。该文档包含 Windows / macOS / Linux 环境准备、个人模型 API 配置、启动验收、数据保护和故障排查，可连同完整项目源码一起交付。

从 GitHub 获取完整项目（包含运行需要的知识库数据）：

```bash
git clone https://github.com/1saachen/xunxu.git
cd xunxu
```

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

智能功能只使用用户自己配置的模型 API。填写 `FITNESS_API_KEY`、`FITNESS_BASE_URL` 和 `FITNESS_MODEL` 后重启服务；不再使用 `FITNESS_LIVE_ENABLED` 环境变量或模式切换。未配置时可保存档案与原始反馈、查看历史，生成接口返回 503 配置提示。档案、计划、反馈和建议写入本地 SQLite，知识检索读取 `data/knowledge/` 中已批准的内容。

## 隔离开发验证

测试使用合成档案、模拟模型和临时数据库，禁止通过真实 HTTP 模型传输调用用户的密钥。历史规则工具仅供内部兼容与测试，不是可选择的产品模式。真实生成验收需要用户自己的 API。

页面和 API 会区分知识状态：`ok` 表示知识快照已保存，`unavailable` 表示知识库文件或策略产物不可用，`capacity_exceeded` 表示知识上下文超过本地快照容量。知识不可用不切换成无模型生成。并发保存冲突会返回结构化错误 `code`，提示刷新反馈或根据最新档案重新生成。

## 导出当前记录

计划、反馈和已生成建议都可以从页面选择 JSON、CSV 或 Markdown 下载，也可以直接调用接口：

```text
GET /api/export/plan?format=json&plan_id=<plan_id>
GET /api/export/feedback?format=csv
GET /api/export/advice?format=markdown&feedback_id=<feedback_id>
```

JSON 保留结构化字段和生成轨迹；CSV 展开常用字段，便于表格处理；Markdown 适合阅读和归档。导出不包含本地密钥、Cookie 或服务配置。

## 个人历史与趋势

历史 API 提供最近 7、14 或 21 天的确定性趋势摘要，包括睡眠、体重、疲劳报告日期比例、训练完成率和饮食执行率，并用于规划上下文；每日反馈页不再展示单独的趋势卡。统计先合并同日反馈，每项指标显示自己的有效日期数；少于 2 个有效日期时标记为“数据不足”，不会根据单日波动作长期判断。

饮食执行率只使用用户明确回答“是否按计划执行”的记录。普通的食物描述、食堂或外卖记录不会自动被判定为成功或失败。疲劳指标表示“有疲劳描述的日期占有确认反馈日期的比例”；没有描述疲劳不等于用户没有疲劳。字段更正顺序来自该字段最后变化的修订时间，补填体重不会让旧训练表现覆盖新的同日记录。详见[历史与记忆说明](history-and-memory.md)。

历史工具提供以下只读 API：

```text
GET /api/history/recent?days=7&end_date=2026-10-11
GET /api/history/recent?days=14&end_date=2026-10-11&issue=short_sleep
GET /api/history/recent?days=21&end_date=2026-10-11&metric=sleep_hours
GET /api/history/trends?days=7&end_date=2026-10-11
GET /api/history/similar/<feedback_id>?limit=3
```

相似历史返回当前日期之前的共享 issue、匹配信号、过去建议及随后明确记录；后续记录不证明执行过建议或构成因果。完整个人历史查询不会受状态页最多显示100条记录的限制。

## 单 Agent 与可选在线模型

Agent 在生成建议时依次调用档案、当前计划、审核知识、近期反馈、趋势、相似历史和局部训练调整预览工具。在线模型可以选择继续读取工具并表达建议；本地工具负责事实与计算。基础训练处方、来源快照、补剂用量和诊断不能由模型直接改写。

复制 `.env.example` 为本地 `.env`，配置自己的 API 地址、模型名和密钥后重启服务。配置、错误与使用量说明见 [Provider 文档](provider.md)。密钥不得提交到 Git。所有生成失败均明确报错并保留旧记录，不回退到本地生成结果。

生成器保留供应商返回的 token 使用量、调用次数和状态；不会在缺少实际定价时估算成本。日志仅含模型、延迟、状态和用量，不记录档案、提示词、Cookie或密钥。

当日尚未完成训练且明确疲劳时，可以展开调整预览并确认减少组数。确认记录保留旧值、新值、触发问题和证据，原始周计划快照保持不变。页面显示已确认变更后的组数。异常症状优先触发停止训练和专业评估，不生成训练调整。

## 导入、备份与恢复

反馈页提供 JSON、CSV、Markdown 文件导入，先展示事实预览，再由你明确确认写入；无效批次不会部分导入，重复批次不会重复记录。Markdown 导出额外保存完整事实 JSON，支持完整往返；旧的纯文字 Markdown 仅恢复其中实际写出的字段。

```powershell
.\.venv\Scripts\python.exe -m fitness.data_cli import-preview --source feedback.json
.\.venv\Scripts\python.exe -m fitness.data_cli backup --database data/local/fitness.sqlite3 --destination <新的备份文件路径>
.\.venv\Scripts\python.exe -m fitness.data_cli restore-preview --source <备份路径> --database <目标数据库路径>
```

恢复需使用预览得到的 source/target fingerprint 和 `restore-confirm --confirm`；请先停止使用该数据库的服务。详细命令与认证、迁移、Docker、官方健康平台的边界见 [数据与部署文档](data-boundaries.md)。当前数据库 schema 为4，新增长期计划和当天计划表，会自动迁移旧表，拒绝高于当前版本的数据库。

## 检索质量与维护

```powershell
.\.venv\Scripts\python.exe -m fitness.evaluation_cli --output-dir data/evaluation/reports
```

命令输出 JSON/Markdown 检索和审核报告；知识不可用或待复核时返回非零退出码。当前小型回归集覆盖14个案例、15个问题，在74张审核卡上首选分类命中率100%、预期卡 top-3覆盖率86.67%、指定误导集合召回0；保留未命中的案例，不把这当作对所有用户语言的保证。

离线字符 TF-IDF 比较没有优于关键词基线；它不是神经嵌入。当前没有测得 embeddings 收益，暂不引入向量数据库。知识审核和 membership 变更流程见 [知识质量](knowledge-quality.md)，指标和局限见 [检索评估](retrieval-evaluation.md)。

## 基本使用流程

1. 在“我的档案”填写目标、身体信息、训练条件、饮食和恢复信息，点击“保存档案”。计划只能基于已保存的档案生成；修改档案后需重新生成旧草案才能确认。
2. 在“长期计划”选择开始日期和训练循环（如推、拉、腿、休息），生成草案并核对阶段目标、训练、营养目标和复盘原则，点击“确认并启用长期计划”。长期计划按版本保存，不要求每周重建；修改档案后需生成并确认匹配新档案的长期计划。
3. 打开“当天计划”，查看今天的训练、三餐食物与份量、估算热量和宏量营养素、费用、替换选择、饮水及恢复安排。可输入今天的疲劳、伤痛、时间或食堂条件，点击“更新当天计划”；已吃的餐次可记录为完成，更新时保留原安排。
4. 在“每日反馈”输入当天训练、饮食、睡眠、疲劳或体重等事实；可以补充本次餐次、能吃到的食物、想吃的食物、预算和已吃内容，核对后确认保存。当天条件只用于当天规划，不会自动成为长期偏好。缺失的训练完成情况保持未知，不能当成已完成。
5. 再打开“当天计划”时读取已有安排；需要重新评估时点击“更新当天计划”，系统结合已确认反馈、长期方案和历史趋势生成新修订。默认未完成训练顺延；疲劳可改恢复日，明确跳过或伤痛可跳过相应训练，伤痛限制跨天保留并影响相关动作。仅在明确恢复后，通过限制下的“确认恢复并重新评估”提交说明解除限制，再更新当天计划；这是用户声明和审计记录，不是诊断或医疗许可。
6. 对已确认的反馈仍可点击“生成今日建议”，按需展开“为什么这样建议”。旧周计划保留在长期计划页的“历史周计划兼容”中，原有记录和接口继续可读。

打开今天页面时读取已有当天安排；在已确认适用长期计划、今天尚无计划时才自动生成。已有计划通过“更新当天计划”主动重新评估；查看页面或保存普通反馈不会自动重排。在线复盘若明确应用了计划调整，则按其决策更新对应日期。应用关闭时没有后台定时任务；历史或未来日期需要主动生成，不会在打开页面时自动写入。长期训练或热量策略的修改需要生成并确认新长期版本，单次反馈不会自动改写总目标。

对应 API 顺序如下：

```text
PUT  /api/profile
POST /api/long-term-plans
POST /api/long-term-plans/{plan_id}/confirm
GET  /api/planning/state
POST /api/daily-plans
POST /api/daily-plans/{daily_id}/meals/complete
POST /api/daily-plans/{daily_id}/restrictions/release
POST /api/feedback/parse
POST /api/feedback/{feedback_id}/confirm
POST /api/feedback/{feedback_id}/advice
POST /api/nutrition/plan
POST /api/nutrition/memory/preview
```

生成请求只接受 `mode: "live"`，省略时默认使用模型。未配置密钥返回 503，传入 `demo` 返回 422。反馈草稿示例：

```json
{
  "text": "今天完成训练，昨晚睡了5小时，午餐在食堂吃，有点累",
  "date": "2026-09-21",
  "mode": "live"
}
```

## 两层本地 RAG

本项目将知识使用分为两层，两层都只读取 `review_status: "approved"` 的知识卡，并保存当次使用的快照，避免知识库更新后改变历史记录的含义。知识依据保留在 API、导出和后台轨迹中，日常计划页面不默认展开知识卡。

## 饮食规划子 Agent

饮食规划是主 Agent 调用的窄职责模块。它读取已确认档案和当次条件，先用本地计算器生成增肌、减脂或维持目标的起始热量、蛋白质、脂肪和碳水，再按每餐宏量目标组合食物与熟重/份量、替换方式和预算估算。餐项热量由该餐三大营养素估算值核算；具体食物营养、烹调用油、份量和价格仍是近似值，需结合食堂菜单或包装标签复核，不是精确称量或医疗处方。

每日复盘最多使用最近14天反馈：前后两周各至少两次称重、合计至少四次，并有至少四条饮食执行记录且执行率不低于75%，才会判断是否需要复核目标。建议同时展示两周体重均值与执行率，至少再观察14天；反复疲劳等恢复信号会影响解释。减脂停滞且缺少结构化饥饿感/训练表现记录时，只建议核对份量和记录，不贸然降热量；减脂下降较快且反复反馈疲劳时，可建议约100 kcal/日的小幅回调。增肌目标可根据稳定执行下的体重趋势提出约100 kcal/日的微调建议。信息不足、执行度偏低、健康限制未确认或维持目标时不提出热量调整。复盘只写入当天计划，长期目标不会自动更改；用户需重新生成并确认长期计划后才会采用新目标。

当天“可用食物、想吃什么、已吃内容”优先影响当次餐单。若提供食物与档案已记录的过敏、不耐受或不喜欢项冲突，会先要求核实，确认前不会将清单用于具体安排。档案页可预览长期限制和偏好候选；只有用户勾选应用、核对档案并保存后才持久化。

过敏、不耐受和纯素等限制在组合前过滤。未知过敏信息时只输出待确认问题，不声称食材安全。当天“能吃什么、想吃什么、能点到什么”只影响本次规划；“以后都不要”或明确过敏表达可以由 `memory/preview` 提取候选，但必须由用户确认后手动保存档案，不能由 Agent 自动把临时偏好写成长期记忆。

### 1. 计划：baseline 策略模块

全部已批准知识卡被整理为 7 个可审核的 baseline 策略模块。生成计划时会选择并使用与已保存档案目标相适用的全部模块，而不是从知识卡中任取前 5 条。当前减脂档案通常适用全部 7 个模块；生成的策略库保留各模块的行动规则、限制、安全边界和支撑知识 ID，计划记录保存当次使用的模块快照与来源快照。

### 2. 反馈：独立 issue 检索

已确认反馈会先拆成独立 issue，例如睡眠不足、训练疲劳、饮食执行、体重趋势或补剂问题。每个 issue 默认检索 3 张知识卡；当前三张不能覆盖该 issue 的不同子主题时，可扩展到最多 5 张。这个上限按 issue 独立计算，因此一条包含多个 issue 的反馈在合并去重后，总知识卡数可以超过 5。

知识文件缺失或无效时，计划和建议的核心规则流程仍继续运行，保存的 `trace.knowledge_status` 会标记为 `unavailable`。知识库可用但某个 issue 没有匹配项时，该 issue 返回空来源而不阻塞其他 issue；两种情况都不会伪造来源。创作者内容始终保留为“创作者观点/视频观点”，只作为有适用条件的参考，不会自动转化为个体补剂剂量、诊断或医疗结论。

## 查看保存的上下文与轨迹

计划页面不展示“方案依据”或知识卡。策略和知识快照仍保存在计划记录、API 和 trace 中；反馈建议可由用户主动展开解释。

`GET /api/state` 返回当前应用状态，其中 `plans` 和 `feedback` 分别最多包含最近 100 条记录；它不是数据库完整导出或备份接口。响应中的 `knowledge_status` 表示当前已保存档案对应的知识状态。计划中的 `strategy_context`、`knowledge_context` 和 `source_ids` 位于 `plans[*].data`，计划轨迹位于 `plans[*].trace`；反馈建议的 `knowledge_context` 和 `source_ids` 位于 `feedback[*].advice`，建议轨迹位于 `feedback[*].trace`。反馈流程不使用 `strategy_context`。

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

- [工作日志与路线图](work-log.md)
- [P0–P2 逐项验收与当前限制](p2-completion-audit.md)
- [API 合约](api-contract.md)
- [RAG 计划与反馈集成设计](superpowers/specs/2026-09-21-rag-plan-feedback-integration-design.md)
- [人工维护知识库说明](knowledge-quality.md)
- 可提交的演示档案：`data/examples/demo-profile.json`

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

## 训练 Agent 合成评估

运行 `.\.venv\Scripts\python.exe -m fitness.training_evaluation --output-dir data/evaluation/reports/training-agent`。默认使用受控响应，只验证工程管线。显式添加 `--live` 才使用配置的供应商，始终使用合成档案，不读取个人数据库。报告分别记录自动约束、调用/工具/修订次数、usage、耗时和待人工复核的问题。未执行真实模型质量评估，工程通过不能证明训练安排质量达标。

在线生成长期计划和当天计划时，页面会先逐步显示可读的训练、饮食草稿，再整理和校验为正式计划卡片。草稿不会作为已完成计划保存；失败时保留草稿并标明未完成。可读输出与后续结构化整理共享调用和超时预算，因增加模型调用，总耗时和 token 用量可能上升。演示模式不调用模型。
