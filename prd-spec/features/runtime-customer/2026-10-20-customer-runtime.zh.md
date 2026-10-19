# Customer Runtime 集成

[English](2026-10-20-customer-runtime.md)

变更 ID：runtime-customer。创建/修订：2026-10-20。状态：implemented。

## 背景、目标与范围

公开 Agent Runtime 选择器尚不能调用已实现的 customer 客户端、调度器、ADK 事件投影和持久存储。Agent 初始化先解析本地凭证并创建模型；标准 Harness clone 可以切换引擎和模型。本阶段通过正式注册的 Runtime 组合已有组件，由 HarnessApp 承载服务端构造的 Agent；不是整个 SkyEyes 迁移完成。

本阶段不实现：原生 Agent.tools/回调状态桥、请求 JSON/环境构造配置、Host 模型预算/重试、鉴权、生产数据库装配、wheel/镜像/部署、UI 或客户评测。不兼容配置必须在远端执行前拒绝，后续 P0–P4 仍保留这些任务。

## 需求与设计

- FR-1：注册 CustomerRuntime、CustomerRuntimeConfig；Agent(runtime="customer", customer_runtime_config=...) 在本地 Key 获取、工具准备、模型创建和配置日志之前分流。配置为服务端对象，不进入 Agent 序列化/repr，clone 保留引用。不兼容的 ADK 模型/工具/回调/状态选项明确报错。
- FR-2：持久存储将本地身份绑定到 endpoint、配置、目录和引擎修订。首次远端执行前预留 invocation。只 GET 明确的远端 Session，只有从未执行过才能创建；历史丢失不得重建，不枚举会话。HTTP 前恢复私有亲和值；每次新亲和值持久保存后才允许后续请求。
- FR-3：只发送当前非空文本输入。完整 Host 配置/环境、工具声明/只读 Skill 与异步执行器来自服务端配置。复用已有调度/投影清理，不重试整轮。总期限覆盖准备和执行；清理、数据库释放另有边界，并纳入租约预算。
- FR-4：完整本地事件先写日志再输出；只有验证终态、工具 ACK 和清理后才标记完成。ADK 可能在 Runtime 结束后由另一任务保存：保留 completed，下一轮核对 ADK 中的实际事件后才确认。缺失展示时阻止执行。提供显式展示恢复，仅追加缺失后缀、核验保存，不调用 HTTP/工具；内容冲突、乱序历史拒绝恢复。结果不明和过期占用不重跑、不接管。
- FR-5：标准 HarnessApp 承载预建 customer Agent。请求仅允许相同 runtime，其余覆盖及切入/切出 customer 拒绝。HarnessConfig 环境构建仍仅 adk/codex，等待服务端工厂接入。直接修改/clone 也不能让绑定 customer 的 Agent 切回本地模型。显式 max_llm_calls 拒绝，因为 Host 合同不执行该预算；ADK 默认值不是 Host 保证。

## 任务、测试和验收

| 需求 | 任务 | 验收 | 验证 |
| --- | --- | --- | --- |
| FR-1 | T-1 公开配置/分发/检查 | AC-1 不创建本地模型/获取 Key，clone/序列化安全 | 初始化及修改负例 |
| FR-2 | T-2 客户端恢复/Session 查询、租约历史查询 | AC-2 绑定、重开、亲和保存顺序、历史缺失拒绝 | 客户端与正式 Runtime 测试 |
| FR-3 | T-3 组合现有组件 | AC-3 文本/工具往返、续问、取消、超时、错误不重跑 | 实际 Agent/Runner、Harness HTTP 与模拟 Host |
| FR-4 | T-4 日志和显式恢复 | AC-4 实际 ADK 保存失败后仅恢复展示，不重复工具 | 失败 SessionService 与 SQLite 重开 |
| FR-5 | T-5 Harness 保护、门禁和文档 | AC-5 请求不能改变引擎/模型/配置 | Harness /run、/run_sse |

涉及：veadk/agent.py、veadk/runtime/__init__.py、compat.py、customer/{config,runtime,client,session_store,__init__}.py、veadk/cloud/harness_app/{types,utils}.py、tests/runtime/customer/、Harness 工作流门禁。依赖、前端和生成产物不变。组件合同为 runtime-customer；客户端/存储新增方法同步原双语合同。

必需验证：隔离的 customer/runtime/Harness 专项；两 worker 的 Python 全仓回归，排除显式 Codex/Pi smoke；原 pre-commit；双语合同/链接检查。真实 Host/模型/MCP、PostgreSQL 为 not_run，不把模拟验证算作真实验收。

## 审查与授权

review-spec 不可用，已直接审查：组件复用、不兼容配置拒绝、亲和持久化顺序、ADK 异步保存、取消、重复执行、引擎绑定、兼容和双语一致性。已解决：不能仅因生成器恢复运行就确认展示，必须读取 ADK 实际保存状态；不复制远端 actions，回调桥完成前不使用 Agent.tools。用户此前执行集成蓝图、继续优化的指令覆盖本阶段，最新要求明确授权阶段 commit/push 独立分支，不授权部署。

实现前公开入口不存在，测试收集失败（1 个 ImportError），作为缺失入口基线。风险：Host 配置/schema 仍由服务端负责；本模块不鉴权本地 user ID，也不过滤工具结果正文；不配合取消的工具需要外部隔离。进程退出遗留占用要后续显式恢复，不能直接接管。

实现前扩展审查：标准 ADK HTTP 会设置 custom_metadata=None，Harness 即使没有限制也安装本地次数插件。仅允许空 metadata 默认值，customer 跳过该无操作插件；实际配置 App 次数限制仍拒绝。涉及文件增加 Harness app.py。ADK 工作流 clone 字段（chat mode、空 parent、布尔 rerun_on_resume/wait_for_output）允许，持久预留仍防止重跑。

调整续问前补充源码审查：保留的 Host shared_server.py、studio_session.py 均在推理前拒绝缺失 Session。因此只有首轮定点 GET/创建；续问恢复亲和值后直接使用要求 Session 已存在的协议，避免仅为检查存在性每轮下载不断增长的推理历史。HTTP 拒绝仍阻止该预留轮次，不自动重建 Session。

## 交付证据 — 2026-10-20

范围：父版本 ba8f29de0db750d222b8061cc1fb6efb6ff05426 加本提交的 customer Runtime、客户端/存储入口、Agent/Harness 集成、门禁及双语合同。FR-1–FR-5 / T-1–T-5 / AC-1–AC-5 均已实现，由 tests/runtime/customer/test_runtime.py 覆盖。最终审查核对公开接口、回调拒绝、资源边界、异常恢复顺序和双语一致性，本阶段无遗留阻断项。

| 检查 | 实际结果 |
| --- | --- |
| python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py tests/runtime/customer/test_runtime.py | pass：39 项，7.93 秒 |
| customer、流清理、Harness 次数限制和发布门禁测试 | pass：286 项，31.18 秒，早于最后追加的五条 Runtime 用例；最终全仓已包含它们 |
| python3 /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.codex/run_offline_tests.py -p xdist.plugin -n 2 -m 'not codex_smoke and not piagent_smoke' | pass：7803 项通过、50 项跳过、4 项预期失败、6 个子用例通过；407.35 秒，2 workers |
| /Users/bytedance/Workspaces/VolcengineProjects/veadk-python.worktrees/skyeyes-harness-20261020/.venv/bin/pre-commit run --all-files | pass：原五项全部通过，使用隔离 HOME 和已有本地缓存 |
| Python 3.10 AST、双语 ID、绝对文档链接、git diff --check | pass |
| 本机真实 Harness HTTP → customer HTTP → 执行器/回包 → 实际 ADK 保存回读 | pass：连续两轮；Host/配置/数据为替身，没有云调用 |
| 实际 ADK 最终展示保存失败与 recover_display | pass：无 HTTP 或重复工具执行地恢复缺失展示，之后续问成功 |
| 真实 Host/模型/MCP、生产 PostgreSQL、客户原 20 题、远端 CI、wheel/镜像/部署 | not_run：仍属后续集成和验收工作 |

跳过项不作为验收证据。隔离测试包装器阻止 Python 非本机网络且不加载用户凭证，不声明线上性能收益。已验证 Google ADK Runner 与 Harness HTTP；VeADK Runner.run() 仍默认传入 max_llm_calls=100，会被 customer 拒绝，等待 Host 预算/调用方适配。业务工具回调、鉴权、生产存储及 P0–P4 继续保留。
