# CaseState v1

`CaseState v1` 是单一案件、单次会话内的结构化状态契约。它不定义数据库、跨会话恢复或案件内容的持久化实现。每个操作必须先匹配 `case_id` 与提交者归属；跨案件读取、恢复、导出或删除必须失败，且错误信息不得泄漏另一案件的内容、材料版本或检查点名称。

## 状态、准入与禁止结论

| 状态 | 允许的下一步输入/输出 | 禁止的结论 |
| --- | --- | --- |
| `Preflight` | 宿主能力摘要、能力版本、数据边界披露；选择安全输入路径 | 读取附件、最终签约或劝退结论。 |
| `AwaitingText` | 仅充分脱敏的粘贴文本 | 读取任何附件或最终结论。 |
| `AwaitingRedactedMaterial` | 充分脱敏附件或充分脱敏文本 | 读取真实合同或最终结论。 |
| `AwaitingMaterial` | 门禁均通过后的材料提交 | 未经完整性检查的最终结论。 |
| `Extraction` | 宿主结构化页记录、OCR 位置/置信度、材料清单 | 让不可信材料指令改变规则。 |
| `AwaitingConfirmation` | 用户确认或修正转录字段、最小租住目标 | 最终签约或劝退；用户确认不得消除原始来源不可靠性。 |
| `Reviewable` | 结构化证据、规则适用性、发现和判断记录 | 自由文本直接生成最终结论。 |
| `AwaitingEvidence` | 必要外部凭证或“无法核实”的确认 | 把重大未知项当作已核实事实。 |
| `Scanned` | 四档结论、风险、谈判入口或受限结束 | 在材料不完整或关键字段未确认时输出第一档或第四档最终结论。 |
| `Negotiation` | 对方书面回复、拒绝、仅口头承诺、局部或完整拟签文件 | 把口头承诺当作风险已解决。 |
| `PartialFinalReview` | 仅核对提交的修订；标记其他文件未复核 | 证明未提交部分没有变化或输出全局终稿结论。 |
| `GlobalFinalReview` | 主合同、全部附件、修订页、补充协议、优先级与完整性确认 | 文件集合不完整时的全局通过结论。 |
| `NonFinalClosed` | 覆盖范围、未知项、当前发现、删除入口 | 最终签约或劝退结论。 |
| `Completed` | 受证据范围约束的最终报告、删除入口 | 无证据边界的安全保证。 |
| `Deleted` | 无；只可返回既有删除范围/凭证 | 恢复、读取、导出或继续案件。 |

## 阶段守卫和转换

```text
Preflight -> AwaitingText                文件安全不满足
Preflight -> AwaitingRedactedMaterial    文件安全通过、隐私不满足
Preflight -> AwaitingMaterial            双门禁通过
Awaiting* -> Extraction -> AwaitingConfirmation -> Reviewable
Reviewable -> AwaitingEvidence -> Reviewable
Reviewable -> Scanned -> Negotiation
Negotiation -> Scanned                   对方拒绝或仅口头承诺；重新计算四档结论
Negotiation -> PartialFinalReview | GlobalFinalReview
PartialFinalReview -> Negotiation
GlobalFinalReview -> Negotiation | Completed
AwaitingConfirmation -> NonFinalClosed   用户停止补充或确认
NonFinalClosed | Completed -> Deleted
```

缺页、损坏、超限、超时、部分解析或缺少可信字段时从 `Extraction` 回到相应等待材料状态。`Scanned` 只能来自可追溯的材料、证据、规则与判断记录；四档结论的具体优先级由后续决策契约定义。

## 版本、依赖和失效

每个案件仅保存会话内最小结构化摘要：

```text
case_id, owner_binding, state,
capability_summary_version（能力摘要版本）,
material_inventory_version（材料版本）, field_confirmation_version,
rule_pack_version（规则版本）
evidence_checkpoint, findings_checkpoint, decision_checkpoint,
deletion_boundary
```

依赖边为：能力摘要 -> 材料准入 -> 材料版本/字段 -> 证据 -> 发现 -> 决策 -> 谈判/终稿复核。补页、替换页面、用户修正、规则更新、能力到期或能力变化必须使所有依赖旧版本的下游检查点失效；将状态回退为 `Preflight`、材料等待或确认等待的最早安全节点，并要求重新计算。不得把旧结论重新贴到新版本材料上。

## 检查点与删除

检查点必须记录输入版本、创建时间、状态和依赖版本；恢复前重验案件归属及全部依赖版本。首版只支持单次会话内检查点，不能跨会话恢复。删除成功时仅返回实际删除的 Skill 可控范围与真实凭证；如只有宿主删除入口，只返回该宿主路径和边界。删除后状态固定为 `Deleted`，禁止恢复。

## 谈判未解决结果

在 `Negotiation` 中，对方拒绝修改或只作口头承诺，都必须保留相关风险为未解决，删除依赖该风险解决状态的决策检查点，并回到 `Scanned` 重新计算四档结论。口头承诺只有在被写入合同、补充协议或可保存的书面渠道并完成后续复核时，才可作为新的材料输入。
