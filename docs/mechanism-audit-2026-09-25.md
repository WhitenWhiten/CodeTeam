# CodeTeam 机制实现审计与改进任务

> 后续实施：本文保留修改前的审计快照。M01–M16 的当前实现、行为边界与验收见 [运行机制说明](mechanism-runtime.md) 和 [逐项实施记录](mechanism-progress.md)。

审计日期：2026-09-25。代码基线：2d9a4cb。

范围：对照论文的流程文字、方法正文、算法和提示词，核查活动运行路径。没有读取流程图图片，没有使用跑分、实验结果、语料规模或训练数据来判断完成度。本次只新增审计文档，不修改运行代码，不自动提交。

主要文字依据：[论文 main.tex](../../latex/main.tex) 第 334–446 行，尤其是第 336 行的流程说明、355–397 行的 SDS/Architect/CTO 描述、399–446 行的开发、Git 与 QA 描述。修订中的实验承诺作为补充，不能反过来视为机制已经实现的证据。

## 1. 总体判断

**当前已经是能执行完整闭环的 CodeTeam 框架；主要差距在机制约束的强度和细节一致性，不在缺少整条主流程。**

SDS 确实控制了文件任务、owner 权限和依赖调度；Developer 确实生成文件并接收接口摘要；QA 确实执行 pytest、反馈失败并驱动修复；预算、停止状态、Git 提交和恢复也存在。不能再将当前版本评价为只有角色名字、提示词或空架子。

但正文里较强的表述仍不能整体照单确认：逐候选打分排名、严格的实现接口契约、每批次生成测试、Git 提交作为主要通信通道、最多两次额外 briefing、按最小影响范围修复等，与当前执行语义仍有明显距离。其中包含可复现的逻辑缺陷，而不只是文档措辞问题。

不建议给出“完成 80%”之类百分比。流程节点是否存在、节点是否足够严格、是否逐项符合论文，是三种不同问题。当前状态是“流程覆盖较完整，关键机制保真仍需一轮集中补齐”。

## 2. 按流程文字逐项对照

| 流程阶段 | 已存在的运行行为 | 距离论文的主要差距 | 判断 |
|---|---|---|---|
| 0：需求预处理 | CLI 读取 README，规范标题、列表并过滤部分噪声和代码围栏 | 没有稳定的需求 ID/来源映射；被过滤章节中的子标题与 actionable 围栏仍可能泄漏；直接调用 workflow 不自动走 CLI 预处理 | 基本对应，边界不完整 |
| 1：Architect 竞选 | 按种子打乱偏好，多位 Architect 顺序产生 SDS，后者只看粗粒度模块摘要；可使用 RAG | 非独立同分布采样；非重复主要靠提示词，没有重复拒绝策略；一个 Architect 重试耗尽可中止整个规划，不能只丢弃坏候选 | 主机制存在，容错与多样性约束较弱 |
| 2：CTO 选择与规范化 | 路径/字段别名规范化、owner 映射、有效性过滤、LLM 选择一个有效设计 | 没有强制每候选四项评分、总分排序、明确 tie-break 或依排名回退；越界/异常索引回退首个候选；scores 可缺省 | 差距较大 |
| 3：方案落地 | 按 SDS 建文件树，建立 Git，按 dev_plan 实例化 Developer，写权限校验 owner | repo_tree 中未列入 file_specs 的源码可以永远为空；技术栈主要是规划信息，未形成完整环境/依赖交付契约 | 基本对应，有完整性缺口 |
| 4：受约束开发 | ready queue、depth/fanout/order 优先级、每 owner 一个在途任务、目标源码与依赖 briefs、真实文件写入 | 实现只校验语法和声明名称；不强校验签名或实际 import 边；无额外 brief 请求回合；没有每任务上下文硬界限 | 主机制存在，接口/上下文约束不足 |
| 4：Git 协作 | 真正的 agent branch、结构化 update_reason、串行写入与 fast-forward 整合 | 共用一个工作目录，生成结束才切分支写入；其他代理读取的是内存 BriefManager，而非从提交历史消费更新 | 轻量提交与记录已实现；强通信/隔离表述需补齐或改写 |
| 5：QA | 开发前生成一次测试包；每初始开发批次按依赖选可运行测试；全量复验；临时文件清理、日志保存 | 没有每层/批次重新生成测试；QA prompt 仅直接接收 SDS，未单独接收规范化原始需求；测试自身缺陷无专门修复通道 | 执行闭环已实现，测试演进未实现 |
| 6：归因与修复传播 | 按 traceback/import/声明 API 启发式定位 owner；源文件修复、下游 requeue、最终复验 | “四诊断标准”并非四个独立的实际检查；普通实现错误也可重排下游；多条同文件意见覆盖；接口变化判定过粗 | 有机制，也有需优先修复的偏差 |
| 7：停止与交付 | QA 成功、修复限额、预算耗尽、无进展均有状态；最后一次修复后仍复验 | 成功主要依据自生成 QA；没有完整交付契约证明每个必需文件/配置都有实现；接口变化引发的额外重排缺独立上限 | 终止机制较完整，成功边界需收紧 |

这里“动态开发者分配”应理解为**每项目由选中的 SDS 决定人数与 ownership**。论文相关流程并未要求运行中自动扩缩容、抢占任务或重新分配 owner。当前按计划建队已经覆盖这层承诺；不应把“没有运行中扩缩容”误判为漏实现。

## 3. 核心证据

### 3.1 已落实的机制

- [workflow_async.py](../orchestrator/workflow_async.py) 241–407 行：规划、CTO、初始化、创建 worker、QA 与修复主闭环。
- [schemas.py](../core/schemas.py) 327–404 行：路径、重复文件、owner 一致性、依赖解析、环检查与 Python 限制。
- [scheduler.py](../orchestrator/scheduler.py) 99–187 行：确定性优先级、ready 检查、按 owner dispatch 与完成状态。
- [repo_manager.py](../core/repo_manager.py) 45–67、148–228、569 行起：写权限、原子写、分支整合和结构化 commit。
- [developer_worker_async.py](../roles/developer_worker_async.py) 31–63 行：每个 owner 的任务、依赖摘要收集、接口更新回传。
- [run_tests.py](../actions/run_tests.py) 140–207 行：实际执行测试、安装失败单独报告、临时测试清理。
- [workflow_async.py](../orchestrator/workflow_async.py) 64–161、409–435 行：失败/预算/取消状态、复验、无进展停止。

### 3.2 需要特别注意的偏差

1. **CTO 没有论文里的完整排序算法。** [select_sds.py](../actions/select_sds.py) 94–116 行将无效索引回退为 0，仅转发可选 scores；[llm_openai.py](../core/llm_openai.py) 111–112 行的 CTO schema 只要求 chosen_index，并允许 number。提示词“评分”不等于可验证的逐候选排名。
2. **接口声明并未强约束实际签名。** [generate_code.py](../actions/generate_code.py) 104–121 行只检查函数/类/方法名称存在；错误参数、返回注解或 sync/async 形式不在当前硬检查中。AST 保留签名的已有测试不等于校验声明与实现的签名一致。
3. **SDS 本身仍可接受矛盾接口。** [schemas.py](../core/schemas.py) 的函数条目没有检查 name 与 signature 是否同名、重复同名声明是否冲突；未给 file_specs 覆盖所有必需源码设置反向检查；test_framework 没有语义枚举检查。
4. **QA 是“预生成测试后反复执行”。** [workflow_async.py](../orchestrator/workflow_async.py) 361–369 行初始化测试一次；[qa_agent_async.py](../roles/qa_agent_async.py) 42–99 行负责筛选和执行，没有后续生成回路。可选保留这种更简单的机制，但正文第 442 行需要据实修改。
5. **诊断标签强于诊断证据。** [failure_routing.py](../utils/failure_routing.py) 199–218 行只要识别到源/测试路径就可把 structural_validity 写为 valid；此处没有读取源码重新做语法检查。255–263 行用最近源 traceback frame 定位，也不是严格验证“依赖链最早违约者”。
6. **最小修复范围存在直接偏差。** [failure_routing.py](../utils/failure_routing.py) 310、348 行会给普通故障附上直接 dependents；[scheduler.py](../orchestrator/scheduler.py) 228–254 行无需 public_api_changed 为真也会重排这些条目。
7. **修复信息会丢失。** [scheduler.py](../orchestrator/scheduler.py) 220–225 行每次覆盖 payloads[file_path]，同一文件多条失败仅留下最后一条；上层 diagnostic/scope 元数据也没有完整并入开发任务。
8. **接口变化近似不等于兼容性变化。** [ast_utils.py](../core/ast_utils.py) 15–36 行收集所有顶层函数/类，包含私有 helper 和 docstring，未表达模块常量、属性、重导出和共享配置；[generate_code.py](../actions/generate_code.py) 124–135、265–275 行据此判 delta，invariants 默认空。
9. **Git 目前是审计记录，brief 才是运行通信。** [developer_worker_async.py](../roles/developer_worker_async.py) 49、56–63 行直接读写 BriefManager；[generate_code.py](../actions/generate_code.py) 226–275 行在同一写事务中写 commit 并返回 brief，没有提交消费/回放机制。不能说没有 Git，也不能据此声称消息主要经 Git 传递。
10. **上下文是“裁剪了内容”，尚非严格 bounded。** 所有声明依赖的 brief 都被自动塞入 prompt，无 token 上限、截断证据或可请求至多两个额外 brief 的对话动作；brief 保留 invariants 字段但主路径没有真实填充来源。

### 3.3 本次验证

已有机制回归：执行 10 个测试文件，**58 passed in 31.09s**。包括 SDS、planning artifacts、developer context、scheduler、repair loop、QA routing、Git briefs、framework acceptance、contracts、workspace integrity。含真实本地 pytest/Git 运行；没有调用真实模型服务。

另用内存中的最小双文件 SDS 直接调用活动函数，确认以下反例，不修改项目源码：

| 反例 | 观察到的当前行为 |
|---|---|
| 声明 f(x: int) -> int，生成 f() | 被 _validate_candidate 接受 |
| 实现 import 未声明的 ghost 模块 | 被 _validate_candidate 接受；尚须更晚的执行才可能发现 |
| 两个冲突的同名 f 声明 | 被 validate_sds 接受 |
| 接口 name=f，signature=def other() | 被 validate_sds 接受 |
| 文件树额外包含 ghost.py，但无 file_spec/owner | 被 validate_sds 接受 |
| tech_stack.test_framework=unittest | 被 validate_sds 接受，运行器仍为 pytest 路径 |
| provider.py 普通 AssertionError，public_api_changed=false | provider.py 和 consumer.py 都被 requeue |
| 同文件 first/second 两条失败 | 修复任务仅保留 second |
| 只添加 _private_helper | 被当前 delta 认定为导出符号变化 |
| 修改模块常量 VALUE，函数签名不变 | delta 不记录变化；共享配置传播不能由此保证 |
| 被丢弃的 License 节含子标题/命令围栏 | 子标题和命令仍进入输出 |

这些反例证明的是检查/路由的边界，不推断它们对最终分数的大小，也不证明之后 QA 一定无法发现错误。

## 4. 可逐项实现和提交的改进任务

P0：会影响核心机制承诺是否成立，应先完成。P1：补足论文所述通信/上下文细节或提高机制精度。P2：进一步规范和可观测性增强。每项应独立提交，包含对应回归证据；若发现设计需要分步，以先落数据契约、再落运行行为为顺序。

### M01 — P0：收紧 SDS 的语义契约

- 目标：加入 schema_version；验证 name/signature 一致、同名声明冲突、类/方法引用和歧义符号；明确 canonical 字段与兼容别名冲突的处理；执行器不支持的 test_framework/runtime 组合应明确失败。
- 主要位置：core/schemas.py、core/models.py、utils/sds_normalizer.py、utils/sds_parser.py。
- 验收：冲突声明与无法唯一解析的符号被拒绝；合法同文件引用可用；规范化幂等；旧别名输入有明确转换记录。不要用“任选一个符号”掩盖歧义。
- 注意：不要求自动猜测正确重命名；无法无损修正时可以退回 Architect 或拒绝候选。

### M02 — P0：让实现真正服从接口与依赖契约

- 目标：从声明和代码提取 AST 接口，检查参数种类/默认值、sync/async、构造器/方法等；定义类型注解比较策略；核查可静态解析的本仓库 imports 是否符合已声明依赖。
- 主要位置：actions/generate_code.py、core/ast_utils.py、core/dependencies.py。
- 验收：同名但签名不兼容的代码在写入前被拒绝；错误候选不破坏原文件；合法内部 helper 保留；动态 import 明确标为未知，不假装静态检查覆盖一切。
- 前置：M01。检查语法接口与可解析依赖，不把它宣传为行为正确性证明。

### M03 — P0：补齐文件职责与最终交付检查

- 目标：区分源码、配置/manifest、文档、合法空文件、临时 QA 文件；所有必须交付的文件都要有生产者、owner 或明确的静态生成规则。技术栈依赖能进入 manifest/环境准备，避免只停留在描述字段。
- 主要位置：core/schemas.py、core/repo_manager.py、orchestrator/workflow_async.py、actions/run_tests.py。
- 验收：遗漏的业务源码、空配置文件阻止成功状态；允许有意为空的 __init__.py；声明依赖的文件不能因为不在 file_specs 而永久视作无需实现；临时 QA 测试仍不进入交付树。
- 前置：M01。执行环境错误与源码错误继续分别记录。

### M04 — P0：把候选失败变为可审计的淘汰

- 目标：逐次保存候选的 raw/parsed/normalized 状态、错误和修复次数；一个 Architect 耗尽局部重试后继续其余 Architect；在达到预声明的最少有效候选数时进入 CTO，否则清楚失败。
- 主要位置：orchestrator/workflow_async.py::_collect_sds、actions/generate_sds.py、core/llm_openai.py。
- 验收：第一个候选无效、后续有效时仍能完成选择；所有候选无效时不创建伪方案；全局预算仍可立即终止；已生成候选不会因后续失败丢失记录。
- 同时明确 parseable first-pass 与“自动 JSON 修复后通过”是不同状态，避免混作一次成功。

### M05 — P0：实现可核查的 CTO 比较选择

- 目标：对每个有效 candidate_id 返回四项 0–2 整数分数、理由与假设；程序计算总分和稳定 tie-break；保留归一化前后的候选身份及拒绝原因；无效选择输出重试或明确报错。
- 主要位置：prompts/cto_prompt.md、actions/select_sds.py、core/llm_openai.py。
- 验收：每候选均有评分、总分可重算；同分的 fan-out/假设规则能复现；越界或小数索引不再静默采用首个候选；候选失效有确定的下一候选处理策略。
- 前置：M04。可以先规范化全部候选再排序，但应把正文的“选后规范化失败回退”同步为实际顺序，避免造一个没有必要的失败分支。

### M06 — P0：补全 QA 的需求输入和分阶段测试

- 目标：QA 接收规范化原始需求、SDS、已完成批次和可用接口版本；在预声明阶段生成增量测试并保留旧回归测试；让 test bundle 标注所依赖的源码/fixture；为测试自身的语法、错误接口引用等提供有限修复通道。
- 主要位置：actions/generate_tests.py、roles/qa_agent_async.py、prompts/qa_prompt.md、orchestrator/workflow_async.py。
- 验收：未进入 SDS 摘要的原始需求仍可被 QA 看见；两个开发批次有可识别的新测试版本；conftest/fixture 不因 readiness 筛选被丢掉；测试修复不能无记录地删掉失败断言，所有轮次保存来源和改动理由。
- 若选择保留“一次生成、多次执行”，必须直接收窄论文描述；它是合理设计，但不是目前正文声称的逐批次生成。

### M07 — P0：让失败定位有证据且不丢修复意见

- 目标：QA、scheduler、brief 使用同一依赖解析器；真正记录语法/API 检查结果；结合 traceback、owner 与依赖方向给出可追踪定位；聚合同文件所有失败与诊断，不覆盖前一条；歧义保留为 unknown。
- 主要位置：utils/failure_routing.py、orchestrator/scheduler.py::requeue_from_fixes。
- 验收：文件路径依赖和符号别名依赖得到一致路由；结构检查未执行时不得标 valid；同文件多个失败均进入修复 prompt；测试本身和外部环境故障不误派给任意 Developer。
- 前置：M01；可与 M06 分开落地。

### M08 — P0：修复最小重排与接口版本传播

- 目标：区分“重新测试下游”和“重新生成下游”；普通内部逻辑错误默认只修 owner 文件；确有公共接口、导入路径或共享配置影响时才重排受影响消费者；使用版本化 interface diff 记录原因。
- 主要位置：core/ast_utils.py、actions/generate_code.py、orchestrator/scheduler.py、orchestrator/workflow_async.py。
- 验收：普通 AssertionError 不重写 consumer；私有 helper/docstring 改动不等同于 public API break；常量/配置、导出、属性、重导出按明确规则追踪；多个上游变化的理由合并；每个 requeue 都可定位到触发版本。
- 前置：M02、M07。对无法判定的语义影响采用明确的保守复验，不声称静态分析能推断所有行为变化。

### M09 — P1：打通提交记录与接口通信

- 目标：更新消息关联 commit SHA、源码 hash、API 版本、parent 版本；brief 索引成为可由持久化事件/commit 重建的缓存；消费者记录读到的版本，发现过期上下文可重新请求。
- 主要位置：core/repo_manager.py、core/brief_manager.py、roles/developer_worker_async.py、actions/request_briefing.py。
- 验收：清空内存索引后可重放同样的接口信息；提交失败不能发布已接受的接口版本；提交、brief 和消费记录能双向追踪。
- 边界：现有 branch 是真实的，但共享 worktree 只在写入时串行切换。若保留“独立工作区并发开发”的更强表述，再独立增加 worktree/快照隔离；论文仅需轻量分支记录时无需为此重造运行器。当前正文应准确交代共享工作区与写入串行化。

### M10 — P1：实现真正有界的任务上下文与 briefing

- 目标：规定任务输入上限、分段优先级和超限行为；保留目标完整源码的政策应显式化；加入 Developer 可请求最多两次额外 interface brief 的动作，记录请求/拒绝/消费；为 invariants 增加真实来源。
- 主要位置：actions/generate_code.py、actions/request_briefing.py、roles/developer_worker_async.py、core/brief_manager.py、app/config.py。
- 验收：高扇入任务不静默超上下文；超过两次请求明确拒绝；仍不暴露其他 owner 的完整源码；invariants 能追溯至 SDS/需求而非默认空列表；记录被省略的内容和原因。
- 前置：M01、M09。未实现 tokenizer 时须将估算和提供商实际计数分开。

### M11 — P1：把竞选多样性从提示词变为可观察规则

- 目标：为 file-set、API-set、模块边界记录相似度；明确重复候选是保留、重试还是拒绝，以及成本计入方式；识别 src/tests 等通用目录，避免把它们当作真实架构差异；保留偏好、摘要和随机顺序。
- 主要位置：orchestrator/architect_diversity.py、orchestrator/workflow_async.py、actions/generate_sds.py。
- 验收：完全重复的候选有确定处理；合法共享 src/tests 不被误拒；改名字不直接等于结构多样性；用“顺序生成、共享粗摘要”表述实际条件，不能同时声称完全独立采样。
- 前置：M04。不把额外多样性启发式自动宣称为性能改进。

### M12 — P1：完善预算与修复状态机的闭合

- 目标：将候选修复、代码校验重试、接口重排、QA 测试修复分别计数；给接口反复漂移设置可配置停止条件；预算不足输出待完成/待复验清单；这些计数随 checkpoint 恢复。
- 主要位置：orchestrator/workflow_async.py、core/model_usage.py、utils/run_artifacts.py、app/config.py。
- 验收：不会以无穷 requeue 绕开 QA repair 次数；恢复不重置已用预算/重排计数；最后一次修改后有复验或显式 incomplete 状态；“无限 QA 轮数”若加入也仍受全局预算约束。
- 已有 token/call/wall-time 和无进展停止无需重写，基于现有账本补齐子计数。

### M13 — P2：让团队分配带有可检查的工作量依据

- 目标：将论文提到的 coarse workload estimates 落入 SDS；记录每 owner 文件数、依赖链与估计负载；根据执行并发/调用预算校验团队规模；对明显空闲/失衡的分配给出验证结果。
- 主要位置：core/schemas.py、prompts/architect_prompt.md、prompts/cto_prompt.md、orchestrator/scheduler.py。
- 验收：每项目团队大小来自最终计划；负载计算能重算；超并发限额采用排队或退回规划的预声明策略。默认不改变 ownership，不增加运行中自动扩缩容。
- 优化子项：现有 workflow 按批次等待全部完成；可后续改为完成事件即解锁下一文件，在安全快照上触发 QA。小批次屏障本身属于可接受实现选择，不能称整套依赖调度缺失。

### M14 — P2：完善 RAG 的设计信息契约

- 目标：把 README 摘要、树、依赖和接口提示变成带可用性标记的类型化记录；区分已经摘要的内容与原始 README；记录实际注入的片段、顺序与截断；支持固定 retrieval packet 重放。
- 主要位置：rag/rag_client.py、actions/generate_sds.py、actions/select_sds.py。
- 验收：缺少接口提示不会被描述为已提供；查询结果和 prompt 实际内容可逐字对上；top_k 与实际注入上限一致，后端 fallback 继续显式记录。
- 仅处理机制和信息表示；语料采集、污染排除、规模与质量不在此次任务范围。

### M15 — P2：完善需求预处理和需求到测试的追踪

- 目标：修复噪声章节的子标题/围栏泄漏；为需求段落赋稳定 ID 和源文位置；记录保留/删除理由；明确 CLI 与 Python API 的统一输入边界；将需求 ID 传到 SDS、实现和 QA。
- 主要位置：core/requirements_preprocessor.py、app/main.py、orchestrator/workflow_async.py、QA/SDS 契约。
- 验收：被过滤章节不泄漏命令；核心 API/配置示例不会因缺少英文提示词而静默丢弃；重复标题也能唯一引用；相同输入经约定入口得到相同 requirements artifact。

### M16 — P2：提供机制开关与行为证据，支撑后续消融

- 目标：将团队大小、ownership、依赖排序、requeue、brief 更新、Git branch、QA 等拆为显式配置；输出 effective mechanism manifest；关键动作记录 task/owner/依赖版本/测试版本/原因。
- 主要位置：app/config.py、orchestrator/workflow_async.py、experiments/protocol.py、相关策略接口。
- 验收：关闭一项时，其他机制保持约定行为；测试能通过 trace 证明实际移除了机制，不仅改 variant 标签；加入端到端“需求→候选→选择→文件→commit→QA→修复→交付”一致性验收。
- 与 EXPERIMENT_PLAN.md 的 T4 部分重叠，应复用同一实现任务，不重复建两套系统。优先修正 full configuration 后再冻结消融版本。

## 5. 建议实施顺序

1. **契约正确性**：M01 → M02 → M03。
2. **规划保真**：M04 → M05。
3. **QA 与修复保真**：M06 → M07 → M08；其中 M07 不依赖 M06 的完整完成。
4. **信息与资源边界**：M09 → M10，随后 M11、M12。
5. **机制细化与研究可复核性**：M13、M14、M15、M16。

若先做最有价值的一批，优先 M01、M02、M07、M08：它们直接关系到“契约确实约束代码、修复范围确实最小”这两项核心主张，而不仅是工程增强。

## 6. 论文表述应同步澄清的细节

- SDS 的“machine-checkable”首先是计划结构可校验，不能未经 M02 就扩大为所有实现接口和行为均被硬约束。
- CTO 是随机模型调用，不宜将“单个 agent/单次选择”直接称为 deterministic。计划排名可以定义确定性汇总规则，但模型评分本身不因此确定。
- “动态分配”是计划决定团队，不是运行期伸缩；说明人数与 ownership 何时冻结。
- 当前轻量 Git 为分支提交与审计，运行信息经 brief 索引传递；写明真实读写和同步顺序。
- 当前 QA 的模型调用发生在测试初始化；后续主要是运行器与规则路由。若暂不完成 M06，必须改成一次生成、分批筛选、反复执行。
- 声明接口与允许的接口修订之间要有政策：哪些更改禁止、哪些经新契约版本获准、哪些触发消费者复验。
- 展示 source/test/config/document 的边界，避免“固定树”被误解为所有树中节点必然已有可用内容；示例给 Developer 分配 tests 与当前 prompt 禁止此事的冲突也要消除。
- 明确 QA repair round、测试执行次数、Developer generation retry、interface requeue 次数的区别。
- 日志里某个 diagnostics 字段存在，不代表对应检查已执行；区分 checked/failed/not_evaluated/unknown。

## 7. 不应混入此次“本体差距”的项目

换模型、跑正式 benchmark、扩大训练/检索语料、补 SFT 训练、统计显著性、其他系统适配等都有独立价值，但不能用于回答流程机制有没有实现。多语言支持、运行时自动扩缩容、通用终端 Agent、重新规划整个 SDS、浏览器/前端工具等也不是本次按正文核对时必须补的漏项。

本次已有的 58 项回归通过只能说明被覆盖的行为未失败；新增反例说明测试覆盖仍未达到逐条承诺验收。后续每个任务应先保留其可复现反例，再实现并验证修复，最后同步论文中的准确机制表述。

