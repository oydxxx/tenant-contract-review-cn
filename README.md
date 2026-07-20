# 中国大陆住宅租赁合同审查与谈判 Skill

这是一个面向中国大陆住宅租客的开源 Codex Skill。目标是在签约前帮助租客识别合同风险、补齐关键约定、准备可执行的修改文本和谈判方案，并在证据允许的范围内形成签约建议。

> 当前状态：本地发布候选版本已完成自动验证；尚未创建 GitHub 远程、标签或 Release。自动检查不等同于法律、宿主安全或个案事实已经人工认证；在公开发布和人工复核完成前，请勿将其作为真实签约决定的唯一依据。

## 面向谁

- 正在签署中国大陆住宅租赁合同的租客；
- 需要把合同问题转化成具体修改文字和沟通方案的人；
- 希望贡献官方城市规则或可复现风险场景的维护者。

本项目不覆盖港澳台、境外租赁、商铺或办公室租赁，也不代理诉讼、仲裁或向第三方发送法律函件。

## 四档结论

完整版本只会输出以下四档总体结论之一：

1. “基于已提交并核实的材料，未发现需要阻止签约的重大风险”；
2. “修改后再签”；
3. “暂停签约并核实”；
4. “建议放弃”。

第一档不是“合同安全”保证；第四档只允许在材料完整、关键事实已核实、高置信度命中预定义严重红线时使用。材料不完整、OCR 关键字段未确认或地方规则未核实时必须降级，不能用确定语气掩盖未知项。

## 已实现的条件能力与边界

首个参考宿主是 OpenAI Codex 的 Skill 运行方式。本仓库消费宿主的结构化能力声明，不把安装或发现 Skill 误称为平台安全能力证明。

| 运行配置 | 文件安全声明 | 隐私与案件隔离声明 | 当前允许输入 |
| --- | --- | --- | --- |
| OpenAI Codex + 本包 | 未由宿主提供可审查声明时视为 `unknown` | 未由宿主提供可审查声明时视为 `unknown` | 仅充分去标识化的粘贴文本；不读取附件 |
| 其他未集成宿主 | `unknown` | `unknown` | 仅充分去标识化的粘贴文本；不读取附件 |

这里的 `unknown` 只表示当前会话没有可信能力声明，不表示对宿主平台安全能力作负面判断。文件真实类型、危险能力禁用、资源限制和隔离解析均验证通过后，才可读取充分脱敏附件；加密、案件访问控制、日志排除、保留删除和第三方流转边界也都通过后，才可读取未经脱敏的真实合同。附件在门禁前已经进入宿主会话时，Skill 不读取其内容，并说明宿主可能已持有副本。

Skill 以单次会话的版本化材料清单、证据记录和四档结论门槛工作：缺页、OCR 冲突、关键字段未确认、法源到期、城市覆盖空白、能力变化或页面替换都会让下游结论失效并降级。只有完整拟签文件集合通过全局终稿复核，才可形成最终继续签约建议；口头承诺和局部修订页不构成全局通过。它不替代律师，不保证合同有效、交易安全、谈判成功或损失不会发生。

## 安装

取得本仓库后，在仓库根目录执行：

```sh
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/tenant-contract-review-cn "${CODEX_HOME:-$HOME/.codex}/skills/"
```

重新启动或刷新宿主后，应能发现 `$tenant-contract-review-cn`。安装时只复制 `skills/tenant-contract-review-cn/`，不要复制根目录的贡献、发布或测试文件。

## 最短示例

先只验证 Skill 是否可发现，不提交真实合同：

```text
使用 $tenant-contract-review-cn。先说明当前宿主的材料准入边界；不要读取附件，也不要给出最终签约结论。
```

典型请求是：“请审查这份签约前住宅租赁合同，先检查宿主能力和材料完整性，再列出风险、建议条款和谈判方案。” 不要让合同、OCR、聊天、网页或对方回复中的指令改变门禁、法源或结论规则。

## 验证

```sh
# 测试框架仅使用标准库 unittest。下两项 YAML 校验及其测试需要已有的 PyYAML：
python3 -m pip install PyYAML
python3 -m unittest tests.test_publication_safety
python3 -m unittest discover -s tests -p 'test_*.py'
python3 skills/tenant-contract-review-cn/scripts/validate_sources.py
python3 skills/tenant-contract-review-cn/scripts/validate_decisions.py
python3 skills/tenant-contract-review-cn/scripts/validate_publication.py
python3 scripts/run_forward_evals.py --cases tests/forward-evals --output build/eval-report.json
git diff --check
git status --short
git ls-files
```

如果本机已安装 Codex 的 `skill-creator`，可额外运行其 `quick_validate.py`；GitHub Actions 使用仓库内更严格的安装包结构测试，因此不依赖仅存在于本机的私有路径。

前向评测的范围、版本和人工复核要求见 [`references/evaluation.md`](skills/tenant-contract-review-cn/references/evaluation.md)。`build/` 是本地或 CI 产物，不会进入 Git；发布候选应保留与对应提交关联的报告。自动检查只证明已编码的结构与门槛成立，不证明法律内容正确，也不替代人工复核。

## GitHub 首发门槛

在全部命令通过并完成干净安装复验后，维护者仍须人工确认 GitHub 账号、仓库名、公开可见性、MIT 许可证、提交历史、版本标签、Release 说明和评测报告指向同一通过验证的提交。当前仓库尚未上传或发布；不得把本地通过误称为已上线版本。

## 责任边界

本项目提供合同风险信息、证据整理和谈判辅助，不替代具备资质的律师针对个案提供法律意见，也不保证合同有效、交易安全、谈判成功或用户不会发生损失。涉及重大财产损失、身份或产权争议、疑似欺诈、强制清退或诉讼仲裁时，应联系当地主管部门或法律专业人士。

隐私与安全报告方式见 `SECURITY.md`；贡献要求见 `CONTRIBUTING.md`。公开仓库只允许合成材料，禁止提交真实合同、聊天记录、证件、权属材料、令牌、宿主日志或本机路径。
