# Model-led Training Agent Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task in the current session. Steps use checkbox syntax for tracking. Do not delegate unless separately authorized.

**Goal:** 让现有训练子 Agent 在 live 模式下通过工具生成和修订完整训练方案，接入长期与当天计划，并保留可靠的状态、确认和版本管理。

**Architecture:** 保留训练、饮食、主入口的专业职责划分。新增共用模型运行循环，训练角色使用只读工具和候选校验；应用负责执行事实、版本和保存。本阶段饮食保持明确标记的本地规则来源，不声称已经完成多 Agent 自主协作。

**Tech Stack:** Python 3.11、Pydantic v2、FastAPI、SQLite、httpx、pytest、原生 JavaScript、node:test。

---

## 实施状态（2026-10-20）

第一阶段代码、API、页面与离线评估已交付；下方原始细分步骤保留为设计检查清单，不逐项追认未单独执行的测试命令。实际验证记录如下：

- [x] Task 1–2：严格训练契约、共用运行循环、预算与受限传输；覆盖修订、工具权限、超时、调用/工具上限、非法 JSON 与超大输出。
- [x] Task 3–5：状态拆分、只读工具与完整模型训练输出；旧 live action/fallback 预期已迁移。验证模型4组保留、器械冲突后修订、安全停止和显式跳过。
- [x] Task 6–8：长期/当天服务、事务快照、追问错误与页面；验证已执行保留、反馈保存与规划失败分离、原模式刷新、无自动失败重试。
- [x] Task 9：8例合成数据、默认离线/显式 live 评估入口、JSON/Markdown 报告和文档。
- [x] Task 10 工程验证：Python 592 passed，前端34 passed；Ruff、compileall、两个 JavaScript 语法检查、git diff --check 通过。两条 Python 警告来自 Starlette/httpx 与 anyio 弃用；Git 只有已有换行转换提示。
- [x] 临时 SQLite 集成覆盖模型4组保存、长期确认、当天生成、反馈修订、失败不写入、已吃餐次保留及重新打开数据库读取。
- [ ] 真实模型质量评估：2026-10-20 仅用合成当天任务做过一次真实 DeepSeek 管线验证（5 次调用、约 18,890 tokens，候选通过校验）；完整 `--live` 评估未执行，离线报告不能证明模型规划质量。
- [ ] Git 提交：工作区混有实施前已有变更，保留原分支和修改，未整体提交或推送。

实施偏差：候选验证测试集中在 test_training_tools.py、test_training_live.py 和服务测试，未另建 test_training_validation.py。持久化验证通过自动化临时数据库测试完成，未手动操作浏览器。完整复杂症状理解、单侧/计时动作的精确耗时和专业合理性仍需评估；新 live 路径对未明确的活动限制保守暂停。饮食模型规划和主模型委派仍属后续阶段。

## 依据、范围和工作区保护

依据：`docs/superpowers/specs/2026-10-20-model-led-agent-harness-design.md` 的第一阶段。用户已同意训练负责训练、饮食负责饮食、主 Agent 负责协调，工程提供 harness。这里的边界是职责与权限，不是固定当前类和函数实现。

当前工作区有尚未提交的长期/当天计划、训练模块等代码；实施前保存各相关文件的 diff 和未跟踪文件清单，逐项复用，不执行 reset、clean 或覆盖式重新生成。只提交本任务拥有且已核对的变更；混有已有修改的文件先按内容审阅，不使用 `git add .`。本计划本身不代表测试已执行或业务实现完成。

交付范围：

- live 长期训练循环与当天完整训练候选，模型查询工具并按校验错误修订。
- 原有 demo 行为、完成与跳过事件、持续限制、解除时间、已执行内容、版本冲突。
- API 与页面识别就绪、缺信息和失败；模型失败不保存规则替代结果。
- 合成档案的评估入口，分别报告工程正确性与模型规划质量。

本阶段不实现模型饮食规划、主模型委派、子 Agent 递归、后台任务或独立持久化聊天系统。后续追问以补充 conditions 后重新生成实现；每次建立新的 run_id，检查上一轮返回的快照标识，不假装恢复了未保存的模型对话。

## 文件职责

以下路径均相对仓库根目录 `E:/Learning/fitness-assistant`。

| 文件 | 工作内容 |
| --- | --- |
| `fitness/agent_contracts.py`（新增） | 运行状态、预算、校验问题、结果与可序列化错误 |
| `fitness/agent_runtime.py`（新增） | 共用模型/工具循环、修订、计时和轨迹 |
| `fitness/training_contracts.py`（新增） | 训练任务、循环/当天候选与强类型字段 |
| `fitness/training_state.py`（新增） | 从当前训练模块提取事实、限制与时间语义，不含普通训练处方策略 |
| `fitness/training_validation.py`（新增） | 候选结构、器械、时间、来源和明确限制检查 |
| `fitness/training_tools.py`（新增） | 训练角色只读查询和预览校验 |
| `fitness/training_agent.py` | 保留专业入口，区分 demo 与模型规划 |
| `fitness/config.py`、`fitness/provider.py` | 预算、输出大小与剩余时限支持，保持旧调用兼容 |
| `fitness/daily_planning.py`、`fitness/plan_store.py` | 快照、模型候选适配、保存及过期输入检查 |
| `fitness/daily_models.py`、`fitness/main.py` | 补充条件、快照参数和结构化运行错误 |
| `fitness/static/daily-plans.js`、`fitness/static/index.html` | 说明、来源、追问和失败的最小展示 |
| `fitness/training_evaluation.py`（新增） | 合成案例与显式 live 评估 CLI |
| `tests/test_agent_runtime.py`、`tests/test_training_live.py`、`tests/test_training_validation.py`、`tests/test_training_tools.py`、`tests/test_training_live_api.py`（新增） | 新运行路径的关键回归 |
| 现有训练、当天计划、provider 和前端测试 | 保留真实状态约束，更新旧 live fallback 预期 |

## 共同契约

共用类型与接口在 Task 1 定义，后续任务按此实现，不自行改名：

```python
# fitness/agent_contracts.py
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class RunResult:
    run_id: str
    status: Literal['draft_ready', 'needs_input', 'failed']
    candidate: dict | None = None
    questions: list[str] = field(default_factory=list)
    reason_code: str | None = None
    trace: dict = field(default_factory=dict)

class PlanningRunError(Exception):
    def __init__(self, result: RunResult, snapshot_token: str):
        self.result = result
        self.snapshot_token = snapshot_token
        super().__init__(result.reason_code or result.status)
```

模型最终 JSON 为 `{status, candidate, questions}`。`draft_ready` 必须有且只有与本任务类型匹配的候选；`needs_input` 必须有明确问题且 candidate 为 null；模型不能通过宣称 draft_ready 跳过校验。failed 由运行器生成，供应商错误不得伪装为需要用户补资料。

训练候选不接收任意 SQL、文件路径、profile 修改或已完成声明。公共字段为 `summary`、`assumptions`、`source_ids`、`questions`。循环候选增加 `cycle`；当天候选增加 `action`、`training`、`reasons`、`scheduled_time`、`load_description`。`action` 允许 train/rest/defer/skip/pause；训练中减量或替换以实际动作和 reasons 表达。

`TrainingStep` 包含 label、kind、exercises、estimated_minutes，exercises 使用现有 `Exercise` 类型；数值做严格校验，不能把字符串或布尔值当组数。循环最多14步、每步最多8个动作。rest、defer、skip、pause 不能携带待执行动作；train 必须有动作。模型不生成 cycle_index、next_cycle_index 或 restrictions 的解除记录。

根任务默认预算：12次模型调用、20次工具执行、每个候选最多2次修订、180秒总时限。模型调用失败也计数；只累计供应商实际返回的有效 usage，不重复加 provider 的全局累计值。

## Task 1：运行与训练契约

**Files:** 新增 `fitness/agent_contracts.py`、`fitness/training_contracts.py`、`tests/test_training_live.py`；修改 `fitness/config.py`。

- [ ] 添加严格训练类型：`TrainingStep`、`CycleCandidate`、`DayCandidate`、`TrainingTask`，以及 `RunLimits`、`ValidationIssue(path, code, message)`。TrainingTask 注入日期、档案与版本、长期计划、执行进度、限制事件、原始条件、确认历史、只读快照标识；时间字段保留来源。
- [ ] 在 `tests/test_training_live.py` 写以下最小契约测试；运行 `.\.venv\Scripts\python.exe -m pytest tests/test_training_live.py -q`，确认因缺少新契约而失败。

```python
import pytest
from pydantic import ValidationError
from fitness.training_contracts import TrainingStep

def test_rest_step_cannot_hide_exercises():
    with pytest.raises(ValidationError):
        TrainingStep.model_validate({
            'label': '恢复', 'kind': 'rest', 'estimated_minutes': 10,
            'exercises': [{'exercise_id': 'squat', 'name': '深蹲',
                'sets': 3, 'reps_min': 8, 'reps_max': 12, 'rest_seconds': 90}]})

def test_string_sets_are_not_silently_coerced():
    with pytest.raises(ValidationError):
        TrainingStep.model_validate({
            'label': '腿', 'kind': 'training', 'estimated_minutes': 15,
            'exercises': [{'exercise_id': 'squat', 'name': '深蹲',
                'sets': '3', 'reps_min': 8, 'reps_max': 12, 'rest_seconds': 90}]})
```

- [ ] 为每个状态增加互斥字段测试，覆盖空 train、非法 reps 范围、额外写入字段、未知 action、NaN、无问题 needs_input。按现有 `Contract` 的禁止额外字段约定实现。
- [ ] Settings 新增 `agent_max_calls=12`、`agent_max_tools=20`、`agent_max_revisions=2`、`agent_timeout_seconds=180`、`agent_max_output_tokens=4096`，逐个提供同名前缀 FITNESS_ 的环境变量及有限正数/整数校验；旧 max_steps 继续用于未迁移建议路径。
- [ ] 重跑契约与 `tests/test_provider.py`；验收：旧配置可加载，新状态和训练数据不能歧义解析。

## Task 2：共用模型循环与受限传输

**Files:** 新增 `fitness/agent_runtime.py`、`tests/test_agent_runtime.py`；修改 `fitness/provider.py`、`tests/test_provider.py`。

接口契约：构造器为 `AgentRuntime(provider, limits, *, clock)`；执行入口为 `run(*, role, task, tools, validate) -> RunResult`。tools 实现 schemas/call；validate 接收候选和本次工具引用集合，返回 ValidationIssue 列表。clock 是可替换的 monotonic 函数，用于测试预算和 deadline；生产调用显式传入 time.monotonic。

- [ ] 先添加脚本 provider 测试：依次返回 get_training_history 工具调用、非法候选、修正候选。核验工具消息对应 call_id、校验错误回传、只接收修正候选、调用数与 usage 为三次实际返回之和。测试使用显式固定响应，不依赖真实网络。
- [ ] 运行 `.\.venv\Scripts\python.exe -m pytest tests/test_agent_runtime.py -q`，确认新循环缺失导致失败。
- [ ] 实现循环：生成 run_id；记录 monotonic deadline；每次调用前检查预算；工具只用 schemas 白名单并二次校验参数；结果限制大小；保存工具轨迹；最终 JSON 使用 provider 的重复键/非有限数拒绝解析；调用 validate；把结构化问题发回模型；修订耗尽返回 failed。任何保存由调用者完成。
- [ ] `OpenAICompatibleProvider.complete(messages, tools=None, *, timeout_seconds=None, max_output_tokens=None)` 增加可选覆盖参数，默认保持旧行为；正数上限检查；runtime 传 min(单次配置, 根任务剩余时限) 与训练输出 token 限额。httpx 读取每个 chunk 前后检查根 deadline，返回后再检查，防止超时后仍接受结果。说明同步传输取消受底层阻塞超时约束，不声称可实时中断任意自定义 provider。
- [ ] 覆盖 call/tool/revision 上限、deadline 前后、provider timeout、非法工具、错误 JSON、超大工具返回、needs_input、缺 usage、已返回 usage 后校验失败。非法权限工具立即 failed；普通参数/候选错误允许在预算内修订。错误不能携带完整 prompt 或密钥。
- [ ] 运行 `.\.venv\Scripts\python.exe -m pytest tests/test_agent_runtime.py tests/test_provider.py -q`；验收：错误可追踪、无未授权工具执行、无任何自动 baseline 回退。

## Task 3：从规则规划中分离训练状态

**Files:** 新增 `fitness/training_state.py`；修改 `fitness/training_agent.py`、`fitness/daily_planning.py`；复用 `fitness/feedback_facts.py`；扩展 `tests/test_training_agent.py`、`tests/test_daily_plans.py`。

接口契约：`resolve_training_state(*, profile, day, history, restrictions, conditions, conditions_recorded_at) -> dict`。返回 confirmed_facts、active_restrictions、release_events、urgent_stop、current_intent、recovery_signals；信号包含日期和来源，不返回动作或组次。

- [ ] 先以现有原始描述时间、字段修订时间、逐部位解除及再次报告样例添加分离状态的特征测试：后来的食物记录不删除旧伤；解除肩部不解除膝部；疲劳恢复不解除伤痛；原始伤痛不会因写建议被重新标成新报告。运行失败，证明接口尚未存在。
- [ ] 将 `_timestamp`、`_released`、限制和事件时间处理迁入状态模块；demo 调用相同状态解析后保留原有固定循环和减组策略。现有 `build_cycle(profile, labels)` 默认行为保持兼容。
- [ ] 把近期睡眠/疲劳呈现为带日期、来源和样本数的输入；live 不先执行本地短睡眠减组、连续疲劳必顺延等策略后再让模型选 action。显式停止/跳过意图与安全停止仍作为必须遵守的输入约束。
- [ ] 验证空条件不能解除限制、明确再次报告在解除之后重新激活；无法可靠理解的活动限制只标记待澄清，不假定可训练。现有关节标签只能拒绝明显冲突，不能证明受限动作安全。
- [ ] 运行 `.\.venv\Scripts\python.exe -m pytest tests/test_training_agent.py tests/test_daily_plans.py -q`；验收：demo 状态语义无回退，状态模块不生成训练处方。

## Task 4：训练工具和候选校验

**Files:** 新增 `fitness/training_tools.py`、`fitness/training_validation.py`、`tests/test_training_tools.py`、`tests/test_training_validation.py`；读取现有 `fitness/catalog.py`、`fitness/knowledge.py`、`fitness/history.py`。

工具与接口契约：`TrainingTools(task, knowledge)` 的 `schemas() -> list[dict]` 提供供应商工具定义，`call(name, arguments) -> dict` 返回结构化工具结果；实例保存 retrieved_sources 供引用校验。`validate_training_candidate(candidate, task, retrieved_sources) -> list[ValidationIssue]` 返回具体问题，空列表表示可接受候选。预览校验和最终强制校验调用同一函数。

- [ ] 为 get_training_profile、get_training_history(days=7/14/21)、get_training_trend(days=7/14/21)、search_training_knowledge(query, limit<=5)、list_training_exercises(equipment, query)、preview_training_candidate(candidate) 添加显式参数模型。schemas 只使用 provider 已支持的 JSON Schema 子集；复杂候选预览使用有长度限制的 candidate_json 字符串，严格解析后验证，避免未支持的 `$ref` 意外拒绝合法调用。
- [ ] 首先测试历史不能读取任务日期之后的记录、工具无 SQL/写入、知识缺失返回 unavailable、空匹配不伪造来源、查询条数上限。运行 `.\.venv\Scripts\python.exe -m pytest tests/test_training_tools.py -q` 并确认失败。
- [ ] 实现快照只读工具；历史范围在 harness 强制裁剪。检索使用 `search_knowledge()` 并复核批准状态；保存本次返回 source ID 集及快照。工具输入长度和结果总字节数有界，不把所有历史无条件放进 prompt。
- [ ] 添加校验失败案例：未知动作、无器械、超时、休息日含动作、伪造引用、受限部位明确冲突、改变已完成训练、无明确授权的 skip。输出路径如 `training.exercises.0.exercise_id`，不通过改写候选来隐藏错误。
- [ ] 时间检查按每组执行估算与组间休息合计，并标明方法与假设，不能仅接受模型声称 estimated_minutes<=20；现有 catalog 时间不随组数变化，不能单独证明时长。用户当天20分钟限制结构化为本任务约束，模糊时间信息先澄清。
- [ ] 名称以已知动作元数据作显示规范化，保留模型选择的合法动作和组次；未知器械不等于全器械可用。来源必须来自本次提供或检索的集合。
- [ ] 运行两个新测试文件；验收：候选可以区别于本地模板，但必须满足可验证约束；无法核验的身体限制产生 needs_input 或受影响训练暂停。

## Task 5：训练专业角色与完整模型输出

**Files:** 修改 `fitness/training_agent.py`；扩展 `tests/test_training_live.py`。

新增入口，不破坏 demo 的原签名：`TrainingPlannerAgent.plan_cycle_live(task, *, knowledge=None, runtime=None) -> RunResult` 与 `plan_day_live(task, *, knowledge=None, runtime=None) -> RunResult`。runtime 未注入时使用配置和 provider 构造 AgentRuntime；knowledge 不可用时工具明确返回 unavailable，不阻止无引用的合理规划，也不伪造来源。

- [ ] 先写模型输出与固定模板不同的完整循环及当天动作样例；用 fake provider 返回4组而非本地3组，断言最终候选保留4组。再覆盖工具检索后输出、第一次器械冲突后修正、needs_input 和 provider 故障。
- [ ] 运行 `.\.venv\Scripts\python.exe -m pytest tests/test_training_live.py -q`，确认因缺少 live 入口失败。
- [ ] 系统提示说明训练职责、工具使用、真实事实与候选区别、知识引用的资料性质、未知信息语义、完整输出契约和少量硬约束。注入 task 及可用工具，不注入一份强制遵循的规则处方。
- [ ] runtime 使用 Task 4 校验器，允许模型修订动作和组次；needs_input 不调用 demo；live disabled 或 provider 故障返回 failed。紧急停止可以保留固定停止提示与 skipped_safety 轨迹，不记为模型规划成功。
- [ ] 原 `_model_decision()` 受限 action 路径从新 live 入口移除；修改旧 live fallback 测试为 failed 预期，保留 demo 处方测试。涉及安全停止的测试明确核验未调用 provider。
- [ ] 重跑训练相关新旧测试；验收：长期和当天训练内容真正来自模型，完整结构可进入调用者。

## Task 6：长期/当天服务接入与原子保存

**Files:** 修改 `fitness/daily_planning.py`、`fitness/plan_store.py`、`fitness/orchestration.py`；扩展 `tests/test_daily_plans.py`、`tests/test_daily_agent_context.py`。

- [ ] 先加服务测试：live 长期生成调用训练 provider，live 当天动作与模型一致；failed/needs_input 时仓库记录数与旧计划不变。构造 provider 内部变更反馈的场景，保存必须报 Conflict。
- [ ] 运行对应测试，确认现有本地生成路径不满足预期。
- [ ] 在 `create_long_term()` 读取日期快照并构造 TrainingTask，live 调用 `plan_cycle_live()`，demo 保持 `build_cycle()`；返回 candidate.cycle 写入原数据结构。营养仍来自当前模块，trace 明确训练 model、营养 deterministic_local。
- [ ] `PlanRepository.create_long(..., expected_token=None)` 在同一保存事务中验证生成前快照；旧调用无 token 保持现有档案版本检查，新 live 路径必须传 token，涵盖反馈和活动计划变化。
- [ ] `generate_day()` 保留实际完成/跳过的进度派生、限制事件和输入指纹；live 调用 `plan_day_live()`，不从本地规则结果初始化模型动作。保存前再次候选校验和 snapshot token 比较。
- [ ] 已完成训练直接保留事实内容，必要时只重新规划尚未完成部分；不能在模型校验后悄悄替换模型动作。饮食消费最终实际训练，而非已作废候选；已吃餐次保持原记录。
- [ ] failed/needs_input 抛 `PlanningRunError`，不调用 create_long/append_day；成功仍返回旧记录结构以保持 API 消费者兼容，生成状态与各部分来源放 trace。
- [ ] 确认反馈后的自动刷新保持原记录保存成功语义，规划失败单独返回状态；避免现有 `mode='demo'` 自动刷新覆盖此前 live 的训练。沿用该日期最近计划的生成模式；没有计划时默认 demo，并在 trace 明确来源。
- [ ] 运行 `.\.venv\Scripts\python.exe -m pytest tests/test_daily_plans.py tests/test_daily_agent_context.py tests/test_training_live.py -q`；验收：不能写入过时输入，不能重复推进，不能丢失已执行内容。

## Task 7：追问、失败与 API 契约

**Files:** 修改 `fitness/daily_models.py`、`fitness/main.py`、`fitness/orchestration.py`、`fitness/daily_planning.py`；新增 `tests/test_training_live_api.py`。

- [ ] LongTermRequest 增加可选 conditions；LongTermRequest 与 DailyRequest 均增加 `expected_snapshot_token: str | None`（SHA256长度与字符校验）。主入口转发新可选参数，旧调用仍可用。
- [ ] 先用 TestClient 覆盖结果：成功200旧记录；needs_input 为422；供应商/输出失败502；运行超时504；状态版本冲突409。live 未配置继续使用原显式 mode 拒绝语义，不自动改 demo。
- [ ] 错误 detail 统一 `{code, status, run_id, message, questions, retryable, snapshot_token}`；needs_input 的 code 为 planning_needs_input，retryable=false，表示需要补条件。provider timeout/network 允许手动重试；非法工具和输出错误不声称仅重试必能解决。
- [ ] 用户补充 conditions 后以预期 token 重新生成；token 不一致409，提示刷新后重评；相同 token 可建立新 run，不读取不存在的旧模型对话。不存正式计划只为保留追问。
- [ ] feedback confirm 对当天刷新失败返回独立 `planning_update`，不回滚已确认反馈或将整个确认请求标为保存失败。仅捕获预期 PlanningRunError/Conflict，不吞所有异常。
- [ ] 运行 `.\.venv\Scripts\python.exe -m pytest tests/test_training_live_api.py tests/test_api.py tests/test_daily_plans.py -q`；验收：UI能准确区分补信息、供应商失败和已保存事实。

## Task 8：页面最小接入

**Files:** 修改 `fitness/static/daily-plans.js`、`fitness/static/index.html`；扩展 `tests/frontend/daily-plans.test.cjs`。

- [ ] 先写前端测试：422问题安全渲染且旧计划保留；502显示未按本次条件更新；200才显示更新成功；provider ok 对应在线模型；营养本地来源独立显示。运行 `node --test tests/frontend/daily-plans.test.cjs` 确认失败。
- [ ] request 辅助函数保留结构化 detail，run 捕获后呈现 questions 和 retryable，不再只丢一个 message。请求失败不清空输入或已保存记录，不把旧计划当新结果。禁止 innerHTML。
- [ ] 长期表单补充可选条件文本，供模型规划和追问回答；当天继续使用现有条件框。补充后再次提交带上同日期/同任务收到的 token；日期或任务改变清除旧 token。
- [ ] 显示训练 summary、assumptions、模型调用来源及营养规则来源；来源只从已记录 trace 读取。历史缺字段显示未知。成功生成后清空本轮问题/错误标记；简单重试按钮仅重复原请求，不自动定时重试。
- [ ] 运行前端测试及 `node --check fitness/static/daily-plans.js`。验收：无需展示JSON或工具参数，用户可看懂结果、问题和失败。

## Task 9：合成案例评估与文档

**Files:** 新增 `fitness/training_evaluation.py`、`data/evaluation/training-agent-cases.json`、`tests/test_training_evaluation.py`；修改 `README.md`、`docs/provider.md`、`docs/api-contract.md`、`docs/work-log.md`。

- [ ] 建立合成案例：正常长期循环、仅哑铃、当天20分钟、普通疲劳、睡眠记录不足、受限活动待澄清、已完成训练、知识无匹配。每例写明输入、自动约束、预期状态和人工复核问题，避免把精确组次作为唯一答案。
- [ ] 默认 CLI 使用受控响应验证评估管线；只有 `--live` 才调用已配置 provider。严格使用案例里的合成 profile，不读取真实档案数据库，不记录密钥或完整敏感输入。
- [ ] JSON/Markdown 报告包括每例状态、明确约束满足、修订次数、来源支持、实际调用与token、耗时、失败原因；人工复核训练合理性单独保留，不用模型自检冒充独立评审。
- [ ] 运行 `.\.venv\Scripts\python.exe -m fitness.training_evaluation --output-dir data/evaluation/reports/training-agent` 验证离线路径。显式 live 命令为同命令加 `--live`；没有实际执行时报告“未执行真实模型质量评估”，不能声称模型效果达标。
- [ ] 文档写清本阶段是训练模型规划、饮食仍为本地模块；主入口尚未模型委派。记录新增预算环境变量、追问/失败结构和真实评估限制，更新旧设计实施范围说明，避免出现 live 静默回退的相反描述。

## Task 10：最终验证与阶段验收

- [ ] 在阶段开始和结束各运行一次现有定向状态回归，比较新增失败；基线原有失败也要记录，不归咎于未核实的变更。
- [ ] 完成以下验证并检查每条实际退出码：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/frontend/*.test.cjs
.\.venv\Scripts\ruff.exe check fitness tests
.\.venv\Scripts\python.exe -m compileall -q fitness tests
node --check fitness/static/app.js
node --check fitness/static/daily-plans.js
git diff --check
```

- [ ] 在临时数据库运行 demo 与受控 live 完整流程：档案→长期草案→确认→当天→反馈→修订→重启读取；核对模型4组样例确实保存为4组，追问/失败不增加正式计划，早餐和完成训练不被覆盖。
- [ ] 逐条核验设计第一阶段：完整模型训练输出、按需工具、校验修订、明确失败、状态保护、来源标识、用量记录。列出仍属于第二/三阶段的能力，不宣称多 Agent 协作已经完成。
- [ ] 审阅本任务差异及与现有未提交修改的关系；按任务拥有的内容形成提交，不包含用户数据、密钥和无关变更。验收报告列出实际测试结果、真实模型评估是否执行以及剩余限制。

## 设计覆盖与交付边界

| 第一阶段要求 | 实施任务 |
| --- | --- |
| 共用循环、预算与结构结果 | Task 1–2 |
| 持续限制、解除、实际执行事实 | Task 3、6 |
| 只读工具、知识、完整候选校验 | Task 4 |
| 训练模型生成循环和当天动作 | Task 5–6 |
| 追问、明确失败、过期输入保护 | Task 6–8 |
| 工程与真实模型评估分开 | Task 9–10 |

本计划完成后，训练专业规划拥有模型决策权，harness 提供可查询事实、可执行计算、校验与状态支持。饮食模型规划和主模型协作另写对应阶段实施计划，不通过本轮扩大实现范围。
