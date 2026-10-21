# 饮食规划子 Agent 与具体餐单实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让主 Agent 在建立档案时生成有营养目标、份量、预算和替换方式的基础餐单，并能根据当天可用食物、想吃的东西和外卖条件生成当日或当餐建议。

**Architecture:** 保留单 Agent 作为编排入口，由有明确输入输出契约的 `NutritionPlannerAgent` 调用模型，负责判断营养目标并制定具体餐单。模型以结构化数据返回每日目标、各餐食物/份量、营养估算、预算、替换方案和待澄清问题；本地公式可作为参考工具及 provider 故障时明确标注的回退，不能静默覆盖模型规划。程序校验输出结构和已知过敏、不耐受等硬约束；长期记忆仍需用户确认。知识审核和详细依据继续保存在后台快照，日常计划页不主动展示。

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, SQLite-compatible profile JSON, vanilla JavaScript frontend, pytest.

---

### Task 1: 扩展饮食数据契约并写失败测试

**Files:**
- Modify: `fitness/models.py`
- Test: `tests/test_nutrition.py`, `tests/test_models.py`

- [x] 增加 `NutritionTargets`（热量、蛋白质、脂肪、碳水、计算方法、假设、置信度）和餐项估算字段；所有新增字段提供默认值，旧计划 JSON 仍可校验。
- [x] 增加档案中的长期饮食偏好字段：`food_preferences`、`disliked_foods`；保留现有过敏、不耐受和限制字段。
- [x] 增加 `NutritionPlanRequest`，支持 `date`、`feedback_id`、`meal`、`conditions`、`available_foods`、`desired_foods`、`already_eaten`、`budget_amount`、`mode`。
- [ ] 先写测试：旧餐单可加载；目标字段能表达估算与不确定性；请求字段有长度和金额边界；偏好字段能保存。

### Task 2: 实现营养估算工具和模型驱动的具体餐单规划器

**Files:**
- Modify: `fitness/nutrition.py`
- Create: `fitness/nutrition_agent.py`
- Test: `tests/test_nutrition.py`

- [ ] 为营养 provider 协议写测试，覆盖用户目标、缺失个人信息、饮食限制、预算、餐食来源、训练/休息日和单餐重规划输入。
- [ ] `NutritionPlannerAgent.plan()` 调用已配置的模型 provider；模型负责判断热量与三大营养素起始目标，并制定早餐、午餐、晚餐和适用加餐的具体食物、份量、营养估算、费用和替换方案。
- [ ] 提供营养估算工具作为模型参考，不把公式结果强制作为在线最终答案；缺少性别、活动量或目标期限时，模型应表达不确定性或询问关键条件。
- [ ] 输出经现有 Pydantic 契约解析并做必要范围、一致性、餐次和预算检查；校验不负责重新规划或把模型值替换成本地公式值。
- [ ] 过敏、不耐受和其他明确饮食限制作为模型不可覆盖的硬约束；输出冲突时拒绝冲突餐单，返回安全回退或请求澄清。
- [ ] Provider 未配置或失败时可使用当前本地估算和餐单模板作为明确标注的回退；demo 模式保持本地行为。
- [ ] 根据学校食堂、外卖、速食和自炊选择具体菜单；当天条件优先于长期基础条件，`meal` 不为空时只返回对应餐次。
- [ ] 当天条件仅影响本次结果；明确“以后、长期、都不要、过敏、不耐受”的文本只生成待确认的记忆候选，不自动修改档案。

### Task 3: 接入主 Agent 与 API

**Files:**
- Modify: `fitness/orchestration.py`, `fitness/main.py`
- Test: `tests/test_orchestration.py`, `tests/test_p2_api.py`

- [ ] 计划生成通过 `FitnessAgent` 调用 `NutritionPlannerAgent`，保存具体餐单和营养目标。
- [ ] 增加 `POST /api/nutrition/plan`，读取当前档案并接受当天条件，返回只读餐单草案，不写入反馈或长期记忆。
- [ ] 增加 `POST /api/nutrition/memory/preview`，只返回结构化长期偏好候选；只有用户在档案页明确保存后才改变 profile version。
- [ ] 为当前反馈增加“今天饮食条件”入口；主 Agent 可根据已确认反馈的 `food_summary` 和用户额外条件调用规划器。
- [ ] 保留 demo 不调用外部模型；Live 模式调用饮食规划 provider；异常症状、未知过敏和非法输入均返回明确状态或待确认问题。

### Task 4: 调整页面信息层级和展示

**Files:**
- Modify: `fitness/static/index.html`, `fitness/static/app.js`, `fitness/static/review.css`
- Test: `tests/frontend/context.test.cjs`

- [ ] 从日常侧栏移除知识审核入口，保留 `/\#knowledge` 直接访问供维护者使用。
- [x] 计划页默认不渲染“方案依据”和知识卡；知识上下文仍保存在 API、导出和 trace 中。
- [ ] 计划页展示每日目标、每餐具体食物和份量、估算宏量营养素、费用、替换项和待确认事项。
- [ ] 反馈页增加当天饮食条件、想吃的食物、可用食物和餐次选择，并展示餐单草案。
- [ ] 渲染所有用户文本时继续使用安全文本节点，不使用 `innerHTML`。

### Task 5: 文档、回归和验收

**Files:**
- Modify: `README.md`, `docs/api-contract.md`, `docs/work-log.md`, `docs/p2-completion-audit.md`

- [x] 说明营养目标是起始估算，必须通过连续反馈校准；不输出医疗诊断或个体补剂剂量。
- [ ] 说明长期限制、长期偏好和当天条件的边界，以及记忆候选必须确认。
- [ ] 运行完整 Python、前端、Ruff、compileall、JavaScript 语法和 `git diff --check` 验证。
- [ ] 使用当前示例档案生成具体餐单，检查食堂/外卖/过敏/低预算和当餐条件路径。
