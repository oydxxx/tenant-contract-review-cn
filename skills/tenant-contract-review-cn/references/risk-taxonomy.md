# 风险发现分类与记录契约

本契约只定义可审计的风险发现，不以自由文本代替证据、规则或决策。每项发现均绑定同一 `case_id`、`material_inventory_version` 和阶段守卫；材料、字段确认、规则包或宿主能力版本变化时，必须按 `CaseState v1` 使发现及其下游决策失效并重新计算。

## 固定五类

| `category` | 中文名称 | 适用边界 | 典型动作 |
| --- | --- | --- | --- |
| `possibly_unlawful_or_invalid` | 可能违法或无效 | 仅在有效、适用的官方规则和证据支持的范围内表述，不把示范文本偏离当作违法 | 补证、修改或按红线规则处理 |
| `tenant_unfavorable_but_not_necessarily_unlawful` | 未必违法但对租客明显不利 | 产品风险判断，不冒充法律结论 | 给出书面修改建议 |
| `material_term_missing` | 关键约定缺失 | 在已审查范围内记录缺失事实；不声称未提交页面也不存在该约定 | 补充书面条款 |
| `external_verification_required` | 合同外必须核验 | 出租权、代理/转租授权、收费及实际收款关系等，需要最小化外部凭证 | 指定核实对象、问题和所需凭证 |
| `currently_indeterminate` | 当前无法判断 | 材料缺失、OCR 冲突、来源不可靠、规则失效/冲突或地方覆盖不足 | 暂停签约并核实，或输出非最终报告 |

不得新增第六类或用“安全”“低风险”等标签绕过上述类别。严重度、证据强度、置信度、可补救性、未知项和用户目标是独立字段，不能相互推断。

## 每项发现的最低字段

```text
finding_id, category, title, material_inventory_version,
evidence_ids, rule_id, rule_version, applicability,
confidence, consequence, severity, recommended_action,
state_guard, legal_fact, product_risk_judgment, negotiation_advice
```

- `evidence_ids` 不能为空。合同内内容应关联页码、条款位置和必要的短摘录定位；缺失约定应关联已审查范围和缺失事实；合同外事项应关联已提供或已核验的最小凭证。
- `rule_id` 与 `rule_version` 对可能违法/无效、红线和确定性法律信息是必填；没有可用规则时使用 `rule_id: null`，并将 `applicability.status` 标为 `unknown`、`expired`、`coverage_gap` 或 `conflicting`，不得形成确定性法律结论。
- `applicability` 至少记录 `status`、地域、时间、主体和事项；仅给出城市名称不等于地方规则已适用。
- `confidence` 只能为 `high`、`medium`、`low` 或 `unconfirmed`。用户确认转录不改变来源可靠性或冲突状态。
- `consequence` 描述现实后果；`recommended_action` 描述下一步。`legal_fact`、`product_risk_judgment` 与 `negotiation_advice` 必须分开呈现。
- `state_guard` 至少回指案件状态、材料完整性、关键 OCR/字段确认和规则包版本。守卫不通过时，此发现只能支持暂停、补证或非最终输出。

## 必须生成的缺失发现

只要在已经完整审查的适用范围内缺少下列任一事项，就必须生成 `material_term_missing` 发现，不能因没有明显违法条款而省略：

- 押金返还期限；
- 押金扣减范围或扣款凭证/结算依据；
- 维修责任的响应或完成时限；
- 费用标准/算法、交付或返还规则。

若页面、附件或条款范围不完整，改为 `currently_indeterminate` 或 `external_verification_required`，说明尚未覆盖的范围，不能断言“缺失”。

## 红线绑定

只有 `red-lines.yaml` 中预先定义、引用当前有效官方 `legal_basis` 的红线可以参与“建议放弃”。发现必须同时记录 `red_line_id`、成立条件、最低证据是否满足、反证状态、对方是否拒绝补正，以及红线的 `on_refusal_result` 与 `uncertainty_result`。社区候选场景只能提出核验问题，不能单独成为高置信红线或劝退依据。
