# 四档总体结论决策契约

总体结论只能由结构化发现和守卫计算得到，不得从合同、OCR、聊天记录、网页文字或自由文本直接生成。四个允许值为：

1. `建议放弃`
2. `暂停签约并核实`
3. `修改后再签`
4. `基于已提交并核实的材料，未发现需要阻止签约的重大风险`

最后一档不是“安全”“可以签”或交易担保；它始终受已核实范围、剩余未知项、地方规则边界和签前检查清单约束。

## 强制合并顺序

每次材料、字段、规则、证据、发现、谈判结果或终稿文件变化后，从上到下重新计算。低优先级发现不得覆盖先命中的结果。

1. **建议放弃。** 仅当一个预定义红线已经成立，且该发现有高置信度、完整材料和已确认关键事实、最低证据齐备、当前有效且适用的规则、无反证，且对方拒绝补正或没有可接受补救时，输出“建议放弃”。红线的 `on_refusal_result: recommend_walk_away_if_decision_gates_pass` 仍受全部这些门槛约束，不是自动法律结论。
2. **暂停签约并核实。** 任一重大未知、证据冲突、出租/代理/转租权限未知、实际收款关系或收费依据未知、规则过期/撤回/冲突、地方覆盖空白或适用性未核实，均强制输出此结论。红线有未知、反证未消除、最低证据不足或守卫不通过时，必须遵循 `uncertainty_result: pause_and_verify`，不能劝退。
3. **修改后再签。** 仅在前两档未命中且存在可以通过写入合同、补充协议或可保存书面确认降低的风险时输出。口头承诺不算补救；对方拒绝后须重新计算。
4. **限定正向结论。** 只有前三档都未命中，材料完整、关键 OCR/字段确认、来源可靠、规则当前有效且适用、无证据冲突，并且通过阶段守卫时，才能输出“基于已提交并核实的材料，未发现需要阻止签约的重大风险”。

材料不完整、关键 OCR 未确认、字段冲突、规则过期或地方覆盖缺口同时阻断第一档与第四档；在这些情形中应回到第二档，或在不能进入 `Scanned` 时输出 `NonFinalClosed` 的限定报告。

## 守卫与版本追溯

决策记录最低包含：

```text
case_id, outcome, material_inventory_version, evidence_ids,
rule_references (rule_id + rule_version), findings_checkpoint,
decision_state_guard, primary_reasons, verified_scope,
remaining_unknowns, local_rule_boundary, pre_signing_checklist
```

`decision_state_guard` 必须记录 CaseState、材料完整性、关键 OCR/字段确认、冲突状态、能力/材料/规则版本及所有通过/失败的守卫。任何版本不一致都使旧 `findings_checkpoint` 和 `decision_checkpoint` 无效。

## 红线语义

`red-lines.yaml` 的 `on_refusal_result` 和 `uncertainty_result` 是唯一可用的红线结果语义：

- `recommend_walk_away_if_decision_gates_pass`：只在本页第一档全部门槛通过时建议放弃；
- `pause_and_verify`：任何未知、最低证据不足、反证或守卫失败时暂停核实。

不得新增“自动劝退”“默认违法”或其他未受 U4 红线记录支持的法律结论。
