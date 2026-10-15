# Harness 会话资源兼容

[English](2026-10-15-session-resources.md)

状态：用户已授权适配最新 Harness App Server、验证 Studio Skill/MCP 更新后发布镜像。修订：2026-10-15。

## 证据与范围
真实 SDK 无条件跳过静态 SkillToolset；关闭 shell 后，配置的 Skill 没有可用读取器。Host 还误拒绝 studio 前缀的只读 Skill 工具。MCP 单独成功不能证明联合成功。修复工具桥接和 Host 校验，不针对测试问题写特例。

## 要求与设计
- FR-1：关闭 shell 时通过正常 ADK 执行暴露已配置的 SkillToolset 工具。开启 shell 的默认行为保留原生落盘 Skill。桥接读取现有 shell_enabled 运行配置；不改变工具过滤、回调或权限。
- FR-2：可选 AIOpsExtension 每轮组合新的 Host Agent。最新 Harness 管理模型/配置选择与会话持久化，不增加控制器或公共 HTTP 协议。
- FR-3：同会话后续轮次可替换模型、Skill 和 MCP，支持空选择；各轮保持快照，其他会话隔离。撤销工具不进入后续声明与执行器；历史继续保留。
- FR-4：接受带 Host 前缀的只读 Skill 工具名，仍拒绝脚本执行。SDK 不增加 shell 权限，不泄露凭证，不包含私有 Core 源码或提示词。

## 文件、任务与验收
T-1：tests/runtime/codex/test_codex_runtime.py 和真实运行路径测试先复现 FR-1 再验证修复。T-2：runtime/codex/tools_bridge.py 与 runtime.py 修复 FR-1。T-3：私有 Host 仓库中的可选扩展接入及静态/动态联合测试覆盖 FR-2/3/4。现有完整 pytest 与原生 smoke 门禁纳入新增回归。

## 风险与验证
保持普通 SDK 行为并测试 shell 两种状态。工具集创建/关闭沿用调用清理；取消和错误须传播且释放资源。证据不保存凭证。离线测试、本地原生协议测试、5663 Studio/云端真实验收分别报告。真实验收检查仅存在于 Skill 的方法编号、实际只读 MCP 回执、同会话替换/清空、模型替换和历史保留；排除客户 Runtime。门禁与联合验收通过后发布镜像。

## 评审
已完成自审：已有用户授权覆盖实施，无需另行确认。双语范围和标识一致。组件影响：aiops-extension CON-6 记录逐轮组合与 Host 职责；原生桥接仅在关闭 shell 时改变行为。默认 SDK 不增加私有 Core 依赖。

验证（2026-10-15）：SDK 全量 7,128 项通过，50 项跳过、4 项预期失败；真实 Codex 进程 smoke 12 项通过、2 项因缺测试数据库配置跳过。安装后的 Core 与独立 Host 门禁通过，包括 4 项原生 session 资源回归。Studio 页面清空与同时恢复 Skill/MCP 后保存回读通过。5663 云端真实调用和镜像发布仍待完成，未修改客户 Runtime。

## 发行兼容补充

真实安装后的 Core 启动门禁发现：extension 分支遗漏此前已发行的 veadk.aiops.harness、services 与 py.typed。需从已审核提交 8fd2eff5 恢复相同公共适配代码及其离线回归，保留本地源码启动与旧导入兼容；不增加核心算法、默认依赖或全局补丁。Managed 模板仍走最新独立 Host。此项属于本轮SDK升级完整性修复，自审确认在用户授权范围内。

## 已安装消费者兼容自审
Core完整门禁复现两个已发行、显式启用的Studio合同缺失：生成MCP overlay必须调用Agent已有确认处理器，不能另加裸工具集；宿主显式设置扩展标识时，自省接口才声明instructionExtension。恢复这两个通用小钩子，不导入Core、不改变普通Agent行为。添加SDK离线回归并保留Core消费者门禁。另一个Core测试假定ADK卡片总是暴露提示词，但ADK 2.7.1已不再如此：改为比较包装前后真实上游卡片，保留私有卡片不泄露断言。这是在新依赖下验证原不变量，不跳过测试。自审：属于既有兼容授权，门禁前不写云端。
