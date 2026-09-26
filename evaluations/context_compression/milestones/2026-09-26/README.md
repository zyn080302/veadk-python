# 上下文压缩阶段性代码快照（2026-09-26）

用户已暂停进一步优化。本目录保存《最新开源压缩对比报告-2026-09-26.md》的有效代码与成绩对应关系，不包含后续实验候选。

## 当前提交：单轮最佳版本

候选为 `sdk-reader-capabilities-20260926`，在统一版 commit `1568059edd301c02ee9e33a9223c2e4dd2757cc9` 上仅改动 `veadk/context/tool_results.py`、新增 `tests/context/test_reader_capabilities.py` 与 `tests/run_reader_capabilities_gate.py`。普通文本来源只向模型声明实际支持的 read/search 能力；原文保存和执行权限保持不变。

Qasper 原 20 题：**F1 50.98，累计 QA 输入 43,555 token，减少 66.34%**；20 题完成，0 失败、0 自主回查、0 新摘要／embedding。复用索引及 18 条查询向量，历史查询成本 1,971 输入 token，来源建索引成本另计。完整 SDK 门禁 **1126 passed / 5 skipped**。此独立版本尚未评测另外两类场景，不能套用父提交的多轮与长历史成绩。

完整 Headroom 同题 F1 为 51.67、QA 输入 146,947 token；本版本质量低 0.69，输入少 70.36%。仅是开发题单均值，不宣称稳定超越。源码映射见 [reader-capabilities-source-sha256.json](reader-capabilities-source-sha256.json)，真实 QA 计划、结果和冻结哈希见 [reader-capabilities-evidence.json](reader-capabilities-evidence.json)。

## 统一三类版本（父提交）

候选为 `sdk-score-fusion-20260926`，保留评测时的 SDK 源码、回归测试与配置。Git 基线为 `0b3058cc687d6479e58ea7fa133030fcaea1ff8a`；已获取上游更新，但归档提交不 rebase 到新上游，也不自动格式化已评测源码，以免改变成绩对应的代码。

| 固定题单 | 质量 | 累计 QA 输入减少 |
|---|---:|---:|
| Qasper 单轮 20 题 | F1 47.01 | 66.16% |
| 同材料连续多轮：9 会话、20 问 | F1 46.28 | 55.70% |
| LongMemEval 长历史 20 题 | 正确率 85% | 87.00% |

单轮成绩通过 20/20 完整请求等效性核验后复用；连续多轮与长历史来自该统一版本实测。历史完整 SDK 门禁为 **1102 passed / 5 skipped**。哈希和结果数值见 [score-fusion-evidence.json](score-fusion-evidence.json)；源码逐文件校验值见 [score-fusion-source-sha256.json](score-fusion-source-sha256.json)。

## 原理与代码入口

SQLite 保存完整 Session 和原始材料。模型输入按当前问题保留关键词＋向量检索选出的证据，其余旧内容替换成来源引用。两路检索先归一化分数再融合；材料较长时使用父子索引。模型仅在业务需要时调用搜索、分页读取工具恢复原文，不强制回查。

| 能力 | 仓库内路径 |
|---|---|
| 请求预算、压缩投影与恢复 | `veadk/context/manager.py` |
| 规模自适应检索 | `veadk/context/adaptive_retriever.py` |
| 关键词＋向量检索与分数融合 | `veadk/context/_hybrid_index.py`、`score_fusion.py` |
| 来源引用、回查工具与能力声明 | `veadk/context/references.py`、`operations.py`、`tool_results.py` |
| SQLite Session | `veadk/memory/short_term_memory_backends/sqlite_backend.py` |
| SDK / Runner 接入 | `veadk/agent.py`、`veadk/runner.py`、`veadk/models/` |
| 回归与强制发布依赖 | `tests/context/`、`tests/run_context_compression_gate.py`、`.github/workflows/context-compression-gate.yaml` |

混合检索需应用显式绑定 `AdaptiveContextRetriever`，提供异步 embedding 实现，并按授权 Session 调用 `prepare_source(...)` 预索引；仅创建普通 Agent 不等于自动复现本次评测配置。基础 SQLite 用法：

```python
from veadk import Agent, Runner
from veadk.memory.short_term_memory import ShortTermMemory
from veadk.context.adaptive_retriever import AdaptiveContextRetriever
from veadk.context.retrieval import use_context_retriever

memory = ShortTermMemory(
    backend="sqlite", local_database_path="./data/sessions.sqlite3"
)
agent = Agent(name="assistant", context_compression={
    "mode": "auto", "context_window": 256000, "verify_sources": False,
})  # 按实际模型设置容量，模型与凭证由应用现有安全配置提供。
runner = Runner(agent=agent, app_name="my_app", user_id="local-user",
                short_term_memory=memory)
# embedder 由应用提供；完成授权原文预索引后再进入问答。
retriever = AdaptiveContextRetriever("./data/context-index.sqlite3", embedder)

async def ask(question, session_id):
    with use_context_retriever(retriever):
        return await runner.run(question, session_id=session_id)
# 应用退出时关闭 retriever 和 Session 服务。
```

## 验证范围

全部模型实验使用授权 Devbox、5663 测试资源，答题模型为 `deepseek-v4-1-flash-260910`，thinking 关闭；此次归档不新增模型调用。离线 SDK 检查命令为 `python tests/run_context_compression_gate.py -q`，安装依赖及运行测试仍在 Devbox 执行。

输入减少取累计 QA 服务端 usage，包含实际回查引起的后续请求；索引、embedding 和必要摘要成本另计。每类仅 20 题，是已见材料开发子集，非完整榜单；LongMemEval 使用官方提示词、Flash 替代裁判。尚未证明质量与输入两项同时超过完整 Headroom。

这是代码归档，未发布 SDK、未交付 Studio 默认接入、未修改客户 Runtime。冻结 SDK 中的既有外围接入代码一起保留以便追溯，不代表这些路径获得了新增质量评测。构建产物、模型、数据集、SQLite、原始请求／回答及凭证不进入提交；Studio 前端工作区的未提交改动不在这份 Python 快照内，完整发布验收仍待后续进行。

报告原件：`arkclaw-ee-gallery/docs/veADK/压缩/最新开源压缩对比报告-2026-09-26.md`，归档前 SHA256 为 `b60d88b9c9dd6ccf04355ee3398fd5ffc145e050540606886075b255c870077c`。详细方案与预索引说明见同目录《混合检索压缩方案与验证-2026-09-25.md》。

## 本次提交前检查

两个版本在 Devbox 补齐测试安装元数据后重新通过完整 SDK 门禁：统一版 1102 passed / 5 skipped，单轮最佳版 1126 passed / 5 skipped；源码未改变。元数据仅留在 Devbox，不进入 commit。pre-commit 未完整通过，详情见 `commit-checks.json`；不把本地归档视为发布门禁通过。冻结源码保持原样，不应用自动修复。 本机只做源码哈希、AST、敏感值模式和 Git 空白静态检查。
