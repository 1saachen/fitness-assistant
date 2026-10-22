# 计划追问收尾实施计划

**Goal:** 实现已确认的两项追问规则，使成功计划明确结束，安全阻断集中询问。

**Architecture:** 复用 `needs_input` 和候选 `questions`，统一规划提示；表单只展示阻断问题，计划卡片末尾展示可选问题。

**Tech Stack:** Python、原生 JavaScript、pytest、Node test runner。

- [x] 先调整前端回归测试，验证可选问题不再占用追问表单、成功后恢复按钮、保留可选回答上下文；运行确认旧实现失败。
- [x] 修改 `fitness/static/daily-plans.js`：在计划末尾聚合可选问题，表单仅使用 pendingQuestions；更新静态版本。
- [x] 在训练、饮食和补剂规划提示中统一安全生成与集中追问规则，保持安全校验。
- [x] 更新工程文档，运行前端、规划相关后端测试和静态检查，审查最终差异。
