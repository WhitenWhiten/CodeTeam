# CodeTeam 机制实现与验收说明

更新日期：2026-09-25。对应 M01–M16；本文件说明实现机制，不报告模型或 benchmark 效果。原审计见 [机制审计](mechanism-audit-2026-09-25.md)，实施及批量验收见 [进度记录](mechanism-progress.md)。

## 1. 默认执行协议

1. CLI 与 Python API 统一在 workflow.run 接收原始需求。保存原文、规范化文、段落 ID、源行范围和保留/删除理由。噪声章节连同其子标题与围栏一起删除；无法判断是否装饰性的代码/配置示例保守保留。
2. Architect 顺序提出候选，使用不同偏好并共享已有候选的粗摘要。记录首次严格 JSON 可解析性、结构化修复、规范化、机械校验与局部重试。无效候选独立淘汰，不阻断其他候选；有效数量不足明确终止。
3. 比较文件/API/非通用模块集合和不依赖命名的图摘要。重复处理默认 keep（保留并报告），可设 reject 或 retry；后者只使用 sds_retry 允许的次数。图摘要碰撞不代表架构语义等价，改名也不能证明多样性。
4. CTO 对每个有效 candidate_id 给四项 0–2 整数分数、理由和假设。程序按总分降序、假设数、最大 fan-out、边数、原候选序号排序。模型评分不是确定性的；聚合排序是确定性的。候选先规范化校验，再评分选择。
5. SDS 冻结文件生产者、团队和 ownership。未提供粗工作量时补结构启发式，并标明来源；不将其伪装成模型判断或实际耗时。超并发限额采用排队，保留小批次屏障，不声称运行期自动扩缩容。
6. Developer 默认只获得完整目标源码、SDS 契约、依赖接口 brief 和诊断。先检查 UTF-8 字节上限，可删除可选摘要元数据并截取错误长文本；目标源码和必需契约仍过长则明确失败。最多两次额外接口请求，每次一个已规划的其他文件，包含失败/拒绝记录，不提供其完整源码。配置的 full context 消融除外。
7. 写入前验证声明的参数名称/类别/默认值、sync/async、构造器/方法和提供了的注解。前向字符串注解按 AST 规范化，默认字符串与数值严格区分。可静态解析的仓库内 import 必须对应声明依赖；动态或未解析 import 明确保持未知。
8. 接受源码后记录 Git commit SHA（禁用 Git 则为 null）、源码 hash、公共接口版本与父版本。持久化 publish/consume 事件可重建 brief 索引；提交失败不发布已接受版本。写入前核对依赖版本，过期时最多重新收集两次。Git 使用共享 worktree 与串行写入事务，不是每位 Developer 的独立 worktree。
9. 每个已完成源码快照触发增量 QA；原始规范化需求和需求目录独立于 SDS 提供给 QA。旧回归测试保留，新内容使用可被 pytest 收集的版本文件名。已有 conftest 不被隐式覆盖；冲突提议保存在生成记录中。fixture 及其源码依赖均就绪后才执行对应批次。
10. 源码失败按 traceback、明确 import/provider、统一依赖图及实际 AST/API 检查路由。歧义保持 unknown，环境/超时/测试本身的无来源失败不任意派给 Developer。同文件的多条失败、诊断和范围信息合并保留。
11. 普通实现错误只重做其文件，其他消费者复验。已接受的公共签名、导出绑定、导入、属性、共享常量/配置变化才触发已完成下游的保守重排，并记录触发版本；这不是行为兼容性证明。私有 helper、docstring 和方法局部变量不因其内部变化触发重排。
12. QA 修复次数、候选/代码/JSON 重试、接口请求和重排分别记录。每文件重排有硬限额；预算中断保存待完成/待复验清单。恢复优先完成中断的 QA 验收，不跳过已接受源码的验证债务。最终交付检查所有必需文件、合法空文件、依赖 manifest 和临时 QA 路径。依赖按 requirements 声明（可递归包含已规划文件）、PEP 621 或 Poetry 主依赖表解析；注释、项目名称、构建依赖和 constraints 不冒充运行依赖。此处校验包身份，不替代版本求解或安装验证。

## 2. 配置与独立开关

以下都是真实执行策略，保存在 effective_mechanisms.json，不仅是 experiment variant 标签。

| 配置 | 默认值 | 改变的实际行为 |
|---|---|---|
| architects | 4 | 候选数量；1 移除竞争 |
| mechanisms.architect_diversity | true | false 使用同一偏好且不共享已有设计摘要 |
| mechanisms.cto_selection | true | false 直接取首个有效候选，不调用 CTO |
| developer_allocation.dynamic_enabled | true | false 使用 fixed_agents；人数最多为源码文件数 |
| mechanisms.ownership | sds | 可选 round_robin、random；独立于人数，仍保持唯一 owner 与写权限 |
| developer_allocation.max_concurrent | 4 | 活跃开发槽位，超限排队 |
| mechanisms.dependency_scheduling | true | false 采用文件原顺序、忽略 readiness 依赖门槛；依赖契约仍保留 |
| mechanisms.dependent_requeue | true | false 关闭已接受接口变化引起的下游重生成；QA 直接定位修复仍保留 |
| mechanisms.live_briefs | true | false 消费冻结 SDS brief；真实提交事件保留但不更新消费索引 |
| mechanisms.context_mode | compact | full 显式提供其他已物化源文件的完整内容，仍受相同输入上限 |
| git.enabled | true | false 关闭提交和分支；接口事件仍持久化 |
| git.branches | true | false 保留主分支提交、关闭 agent 分支 |
| mechanisms.qa_enabled | true | false 跳过 QA 生成、执行和修复；状态为 generated_unverified |
| mechanisms.qa_repair | true | false 仍生成/运行 QA，发现失败后停止，不重写源码 |
| mechanisms.progressive_qa | true | false 只生成初始测试，继续按批次与最终运行 |
| rag.enabled / rag.roles | false / architect | 只对指定规划角色注入检索信息 |
| context.max_prompt_bytes | 65536 | UTF-8 字节硬限额，不冒称 tokenizer token 数 |
| context.max_brief_requests | 2 | 每个开发任务额外请求上限，配置不可超过 2 |
| max_file_requeues | 8 | 每文件重排限额，恢复不重置 |
| max_rounds | 2 | QA 修复次数；null 必须同时设置全局时间/token/call 上限 |

固定团队与保留 SDS ownership 同时使用时，按原组确定性合并或拆分至目标人数；如果研究要移除架构 ownership，应明确另设 round_robin/random。不要把改变人数和改变分配混作一个机制。

示例：关闭 live brief 更新，保留 Git 和其他默认机制。

~~~json
{
  "mechanisms": {"live_briefs": false},
  "git": {"enabled": true, "branches": true}
}
~~~

在 experiment 条件中使用 variant=no_live_briefs 时必须提供对应配置。已知标签与实际配置不符会报错。自定义标签需要 mechanism_expectations 显式声明并验证预期配置。

~~~json
{
  "condition_id": "static-briefs",
  "variant": "no_live_briefs",
  "config": {"mechanisms": {"live_briefs": false}}
}
~~~

full 是基准条件标签，其实际预算、RAG、模型等仍以配置/manifest 为准。完全去除 SDS 的实验需要独立自由形式基线适配器；本框架明确拒绝 no_sds 标签，不以弱化校验假冒该消融。其他 baseline、训练与正式实验矩阵不是这些机制开关自动提供的能力。

## 3. 检索和需求契约

RAG 记录四类 source_fields_available：README、文件树、依赖、接口提示。原始 README 与已提供摘要有区别；缺失字段不能声称已提供。实际注入的文本、顺序、截断、top_k、字符限额与 hash 保存在 planning/retrieval_trace.json 的 packet 中，Architect/CTO 共用同一 renderer。

将一个完整 packet 对象保存为 JSON 并设置 rag.frozen_packet_file，即可跳过语料/embedding 初始化重放。query_sha256 必须匹配统一入口处理后的需求，且 packet 不得超过配置 top_k/字符限额；不静默重新裁剪固定包。语料质量、泄漏和效果不由该机制证明。

需求目录的 ID 来自段落内容 hash 和重复出现序号；同一原文可稳定复现，并保留起止行。file_specs.requirement_ids 和 QA test_requirements 只允许引用目录 ID。遗漏链接显示为 unmapped，不能当作需求缺失已被覆盖。SDS invariants 包含 statement 与 source 并传入 brief；来源是声明的需求/设计依据，不是自动验证过的行为定理。

## 4. 证据与边界

| 证据文件 | 说明 |
|---|---|
| requirements/original.md、normalized_requirements.md、trace.json、coverage.json | 输入边界、过滤决定、源位置及声明覆盖 |
| planning/candidate_attempts.json、architect_candidates.json | 拒绝/接受、规范化、JSON 修复、重复判定 |
| planning/cto_decision.json、workload.json | 全候选评分、排名、工作量与团队 |
| effective_config.json、effective_mechanisms.json | 实际机制和资源策略 |
| interfaces/journal.json | 可重放发布/消费、SHA/hash/版本、上下文请求与裁剪证据 |
| qa/generation_*.json、generation_state.json、test_history.json、round_*.json | 不覆盖的生成尝试、增量测试版本、执行与路由 |
| mechanism_state.json、events.jsonl | 细分计数、任务派发/完成、上游变更原因 |
| checkpoint.json、repository/delivery.json、repository/final.json | 恢复状态、交付完整性、成功或未验证/未完成状态 |

成功必须同时满足最终 QA 及交付检查。关闭 QA 后生成完整仓库不等于通过执行验证，CLI 保持非成功退出；独立评估器可按生成 artifact 正常评测。

这些规则主要约束 Python 的语法接口、输入信息和执行流程。动态 import、运行期反射、行为正确性、训练兼容性以及模型效果仍须分别验证。公共常量/属性/重导出和声明 __all__ 采用明确且保守的语法跟踪；无法静态判断的行为影响通过 QA 复验，不宣称完备证明。
