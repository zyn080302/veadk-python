# Codex 输入上下文

[English](README.md)

ID：codex-input-context。状态：draft（待实现）。修订：2026-11-26。

负责 `veadk/runtime/codex/input_context.py` 的 RPC 文本打包及 Runtime 接线，不负责模型推理、客户工具、会话存储或审批。

CON-1：包含 shim 标记不超过 1,048,576 Unicode 字符的输入原样发送。超长时在本轮内存保留完整原文，发送有限 Markdown 输入并明确标注片段和全文引用。当前问题和近期证据保持可见，不增加知识库数量限制。

CON-2：`_veadk_read_context(reference: str, offset: int = 0, length: int = 16000, query: str = "")` 返回包含 `status`、`text`、`offset`、`next_offset`、`total_characters` 及可选搜索状态的 JSON 工具结果。机器消费者为 MCP/ADK，结构字段用于准确分页并区分未命中和不可用。每页最多 16000 字符，查询最多 256 字符；整数不接受布尔值，偏移不超过原文长度。只读本轮映射，不用全局缓存、文件或网络。引用不是持久来源编号。

CON-3：分发沿用回调、工具次数/超时及取消。不新增模型阶段、重试或增大截止/cap。原会话记录不改。上下文读取事件不再次进入输入历史，避免递归重复。完整历史超长时，即使恢复旧线程也提供本轮最新来源引用。未知/失效引用明确失败，不能当作事实不存在。

CON-4：不归档高权限指令、既有授权输入以外的凭据或隐藏推理，使用已有可见内容过滤。不归一化指令指纹，真正指令变化仍重建线程。附件与 thinking 分类保持。

验证：`tests/runtime/codex/test_codex_input_context.py`、`test_codex_input_context_smoke.py`，原 unit-tests 和串行 Codex smoke 门禁，覆盖 direct/shim 消费。执行结果与边界见[设计](../../prd-spec/bugfixes/codex-input-length/2026-11-26-context-reader.zh.md)。不宣称云端/客户验收通过。
