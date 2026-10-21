# Training agent evaluation

Mode: scripted

未执行真实模型质量评估；受控响应仅验证工程管线。

| Case | Status | Constraints | Calls / tools / repairs | Usage | ms | Reason |
| --- | --- | --- | --- | --- | --- | --- |
| normal_cycle | draft_ready | True | 1 / 0 / 0 | {} | 3 |  |
| dumbbells_only | draft_ready | True | 1 / 0 / 0 | {} | 3 |  |
| twenty_minutes | draft_ready | True | 1 / 0 / 0 | {} | 3 |  |
| ordinary_fatigue | draft_ready | True | 1 / 0 / 0 | {} | 3 |  |
| missing_sleep | draft_ready | True | 1 / 0 / 0 | {} | 3 |  |
| unclear_restriction | needs_input | None | 1 / 0 / 0 | {} | 4 | planning_needs_input |
| completed_training | draft_ready | True | 1 / 0 / 0 | {} | 3 |  |
| knowledge_unavailable | draft_ready | True | 2 / 1 / 0 | {} | 3 |  |

## Pending independent review

- normal_cycle: 循环频率、训练量与恢复是否合理？
- dumbbells_only: 动作选择与负荷说明能否实际执行？
- twenty_minutes: 真实执行、换动作和单侧动作会不会超时？
- ordinary_fatigue: 调整程度与疲劳信息是否相称？
- missing_sleep: 是否承认未知信息并避免编造睡眠和恢复事实？
- unclear_restriction: 是否暂停并提出有用的活动限制问题？
- completed_training: 是否清楚区分已完成事实和后续建议？
- knowledge_unavailable: 是否避免把无匹配、未提供知识当成引用？

工程约束通过不证明处方适用、真实用时或模型质量；计时动作和单侧动作仍需人工核验。
