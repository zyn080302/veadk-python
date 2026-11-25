# Codex 消息分类

[English](README.md)

组件 ID：codex-message-classification。修订：2026-11-25。状态：SDK 修复和必需本地门禁已验证，未部署。

负责 Codex 转换/最终选择和观测出口的 thought 分类。消费者：Runner、回调、会话历史和 BFF 答案收集器。模型/provider 标记和回调自行产生的内容仍由各自模块负责。

- CON-1：item 开始/完成保留 custom_metadata.phase。notification_to_events 接收可选 item_phases 映射，限定一轮，不用全局状态。delta 按 item ID 关联，完成后删除记录。commentary/partial_answer/未知 delta 在 custom_metadata.text 携带文本，无 content；保持 partial，不持久化。真正 reasoning 保持 Part.thought=True，不按词语推断。
- CON-2：明确 final_answer delta 有普通 text 内容。最终取最后完成的明确 final_answer，否则取最后完成的无 phase agentMessage。批量转换一致。较早候选正文不进入单一最终回调/事件。旧版无 phase delta 等待最终选择；旧调用方无需修改签名。未知 phase 不成为答案。
- CON-3：completion 的 gen_ai.completion.N.type 和 assistant/choice 的 parts.N.type 对 thought 使用 reasoning，否则为 text。已有内容采集控制保持，不新增 reasoning 正文采集。
- CON-4：不新增 I/O、配置、重试、截止或权限。已有取消/错误/工具路径保持。pump 退出时丢弃每轮状态，包含错误路径。会话身份隔离和工具历史不变；不追溯清理旧会话。

验证目标：未变的仓库 Codex0.159.2 和原交付0.162.1。APM 保留原内容字段，分类为新增信息；BFF 可显式消费进度元数据，但不能视为最终正文。上游未标记的普通混合文本缺少权威标记时仍无法分类。

CON-1/2：tests/runtime/codex/test_codex_message_classification.py 和本地真实进程 smoke。CON-3：tests/test_tracing_content.py。CON-4：已有 Codex 取消/轮次测试。强制 unit-tests workflow 自动发现测试。真实客户验收需要另行授权部署。

变更与证据：[已批准修复](../../prd-spec/bugfixes/codex-message-classification/2026-11-25-phase-and-thought.zh.md)。
