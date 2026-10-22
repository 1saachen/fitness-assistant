# 长期补剂规划 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task in the current session. 用户已确认设计，直接执行至验证完成。

**Goal:** 长期计划根据档案和已审核补剂库生成可追溯的补剂建议。

**Architecture:** 新增 fitness/supplement_agent.py，独立契约和校验，复用 AgentRuntime；daily_planning.py 协调并保存候选、可信来源快照及 trace。daily-plans.js 展示建议、来源及追问，不修改旧计划。

**Tech Stack:** Python/Pydantic/FastAPI/SQLite，原生 JavaScript，pytest/node:test。

## Task 1：补剂模块
- [x] 新增 tests/test_supplement_planning.py，运行失败用例确认缺少模块、字段与校验。
- [x] 新建 supplement_agent.py，定义 SupplementItem/SupplementPlan 与 plan_live(profile, knowledge, **context)。加载 build_manifest 中 supplements 批准卡，传入完整卡片与来源；调用 AgentRuntime。
- [x] validate_supplement_candidate(candidate, profile, sources) 校验来源、已有产品覆盖、健康风险和剂量；无来源仅允许已有产品的 needs_review。候选不接受模型自填来源快照。
- [x] 模拟模型验证修订、超时、needs_input、知识不可用，并核查输入包含饮食、预算、记忆与安全元数据。

## Task 2：长期计划集成与失败原子性
- [x] 添加临时数据库用例，覆盖完整草案保存、确认和失败不保存。
- [x] 在饮食模型完成后调用补剂模块；用 `_require_ready` 传播错误，不提前保存。候选、实际引用来源和模型轨迹随 `repo.create_long` 保存。
- [x] 扩展测试模拟模型角色分发，仅新增补剂角色，保持训练和饮食测试语义。
- [x] 运行补剂集成、在线训练、流式计划与状态冲突测试，并通过完整 Python 回归。

## Task 3：界面与进度
- [x] 在 tests/frontend/daily-plans.test.cjs 新增建议、证据来源、未知产品、恶意文本和旧版兼容用例，先观察缺少板块导致失败。
- [x] 在长期计划营养后渲染补剂摘要、已有产品标记、优先级、理由、条件、食物替代、注意事项及可信来源；使用 textContent；视频链接允许 HTTP(S)。
- [x] 追问并入长期表单；AgentRuntime 将补剂流式阶段命名为“补剂建议”。
- [x] 运行完整前端测试。

## Task 4：验证与说明
- [x] 执行 Python 全量测试、前端全量测试、Ruff、编译/语法检查和 git diff --check。
- [x] 逐项复核已批准来源、无剂量、健康条件、已有产品和失败不保存的设计要求。
- [x] 更新 docs/engineering-guide.md、docs/api-contract.md 和 docs/work-log.md，记录功能、实际验证数量和未调用真实模型的限制。
