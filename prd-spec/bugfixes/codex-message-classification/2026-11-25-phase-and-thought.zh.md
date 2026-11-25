# Codex 消息分类修复

[English](2026-11-25-phase-and-thought.md)

变更 ID：codex-message-classification。日期：2026-11-25。状态：SDK 修复已验证，必需本地仓库门禁通过，未部署。

## 证据与范围
线上 SDK 对应源码丢弃 phase，并合并所有完成的 agentMessage。completion 属性、assistant 历史事件、choice 事件也丢失 thought 分类。合成复现已证明这些机制；原始 provider 事件缺失，不能据此确认原事故最早根因。用户已明确要求修复已定位的 SDK 缺陷。其余依赖和 Host 冻结；未授权客户部署或云端重放。

## 要求与设计
FR-1：保留开始/完成事件的 phase，在每轮状态中按 item ID 关联 delta。commentary、partial_answer 和未分类 delta 作为 partial 生命周期事件，文本放入 custom_metadata，不作为答案 Part，也不伪装成 thought。明确 final_answer 的 delta 保持即时流式输出。仅有旧版无 phase 消息时，在轮次结束选择最后完成的一条。中间文本不得进入普通 BFF 答案收集器、output_key 或持久化答案历史。
FR-2：与 Codex 最终选择一致：最后一条明确 final_answer，否则最后一条无 phase 的已完成 agentMessage。后到的旧版消息不能覆盖明确 final。批量与流式一致，reasoning/工具事件单独保留。未知阶段可观测，不按正文猜测。只有选中正文进入 after-model 回调；回调原有权限不变，本次不能分类回调自行产生的文本或上游未标记的混合正文。
FR-3：completion 属性、assistant 历史、choice 观测保留实际 thought 对应的 reasoning/text 分类，不改变已有内容采集开关与范围。
FR-4：不升级依赖，不改超时/cap/预算/重试，不访问凭据，不调用外部模型。用未变制品验证仓库 Codex0.159.2 和原交付 Codex0.162.1。每轮 phase 状态使用可选公开关键字参数，旧调用方仍可调用。旧版无 phase 的流式文字延迟至最终完成可见，这是明确的安全/时延取舍。

契约：[codex-message-classification](../../../specs/codex-message-classification/README.zh.md)。不改共享回调合并函数和其他 Runtime。状态只存在一个 pump 内，在所有终止路径释放；不新增任务、重试或 I/O。

## 任务与验收
T-1 / AC-1：先新增正式 pytest 红测，覆盖 phase 转换、交错、旧版/明确最终选择、批量、thought 和观测开关；仅用合成内容。
T-2 / AC-2：最小修改 runtime/codex/translate.py、runtime.py 和两个观测模块。只有选中答案持久化和回放；工具/reasoning 行为保持。
T-3 / AC-3：执行受影响及较大范围仓库测试、既有强制 CI 发现入口、pre-commit，以及真实本地 Codex 进程加固定 loopback 后端。核首问/追问/历史和错误恢复；不涉及真实模型或客户 Runtime。跳过、环境问题、未执行门禁单列。
T-4 / AC-4：独立 SDK 版本/源码与证据，不覆盖旧制品。未经授权部署和原问题验收，不宣称原线上事故已解决。

## 审查与风险
review-spec 不可用，已人工审查范围、消费者兼容、每轮隔离、未知 phase、旧版回退、观测隐私、清理、双语一致性和可测试性。诊断后用户明确要求修复，作为范围批准。风险：旧版 delta 时延、未标记混合正文无法可靠拆分、回调可独立替换内容。明确保留这些限制，不用关键词掩盖。无前端实现和无关依赖现代化。

## 验证
2026-11-25 在 Python 3.12.13、google-adk 2.7.1、google-genai 2.31.0 上验证。运行依赖原样复用；原交付 Codex 0.162.1 只安装到隔离测试环境。无外部模型调用或 Runtime 写入。

- 同份有效 34 项回归：原 SDK 19 失败、15 通过；修后源码 34 通过。早期测试夹具错误单独保留，不作为缺陷基线。
- 新 wheel 独立安装，从源码目录外运行 Codex 0.162.1：34 通过，含真实进程首问/追问/历史/错误/恢复及 EOF 前最终增量。已有 smoke 首次 2 通过、1 因另一套测试同时运行时的进程全局临时目录断言失败；隔离 TMPDIR 后原失败用例通过，未改断言。
- 仓库 Codex 0.159.2：`python -m pytest tests/runtime tests/test_tracing_content.py -m "not codex_smoke and not piagent_smoke"` 为 642 通过、37 跳过、4 xfailed、16 deselected。`python -m pytest tests/test_llm_attributes_extractors.py tests/test_tracing.py tests/config/test_tracing_config.py` 为 48 通过。跳过/预期失败不算成功覆盖。
- `CODEX_RUN_SMOKE=1 python -m pytest tests/runtime/codex/test_codex_classification_smoke.py tests/runtime/codex/test_codex_runtime_smoke.py -m codex_smoke -p no:xdist`：Codex 0.159.2 下 4 通过，使用隔离临时目录。
- 按授权清理空间后，完整 `python -m pre_commit run --all-files` 通过，包含原固定 Gitleaks 8.24.2 hook、Ruff check/format、dependency-policy 和 YAML-secret 检查。之前三次 ENOSPC 记录保留；另行 Gitleaks 8.30.1 扫描不作为替代。
- 工具编译完成后，使用独立 TMPDIR 执行完整 `python -m pytest -n 2 -m "not codex_smoke and not piagent_smoke" -q --tb=short`：7154 通过、50 跳过、4 xfailed、6 子测试通过，390.21 秒。此前完整运行有 7153 通过和一条源码构建复制失败，该原用例单独复测也通过。所有报告保留，尚未证实此前准确瞬时原因；未放松断言或测试选择。
- SDK → JSON → 未改客户 BFF 收集器的 3 项合成边界场景通过，不等于已部署 BFF/浏览器验收。已核原 SDK、修后源码和独立安装 wheel 使用同组 34 项参数化测试。

候选版本：`1.1.15.dev14+aiopsharness.20261125.thoughtfix1`。`scripts/build_codex_classification_wheel.py` 校验原 wheel 准确摘要，只允许四个已授权 SDK 源码修改，保留其他载荷/依赖元数据并重建版本元数据和 RECORD。已安装 wheel 的四个修改模块与受测源码相同。原 wheel 和依赖制品保留。必需本地 SDK 门禁已通过；候选尚未发布到包仓库或部署，客户部署和线上验收仍是另行授权的步骤。不新增超时、token cap、预算、重试、配置或模型请求格式。未执行客户线上/BFF 验收。
