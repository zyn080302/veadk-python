# 客户事实收尾原因兼容

[English](2026-11-07-customer-factual-closeout-reasons.md)

Change ID: customer-factual-closeout-reasons；日期：2026-11-07；状态：已批准隔离实现。

## 背景、范围与授权

获准的 SkyEyes 事实收尾 Agent 产生三种合法 `skyeyes_result` 原因，但固定 dev21 的 `_display_metadata` 拒绝它们：`model_request_failed`、`turn_deadline_exceeded`、`host_execution_failed`。这已确认的消费兼容机制与原客户中断事故归因分别判断。主代理明确授权准确基线的隔离 SDK 修复、提交、离线 wheel 构建及独立安装验证；基线为 `8b0bc84e7b210468336d97cfcfe4b06b4cd65cf5`。原源码、环境和 wheel 保持。禁止网络、模型/MCP/业务请求、部署或远程 Shell；准确基线离线授权优先于通用 pull/fetch/rebase 要求。

## 要求与设计

FR-1：只为 `veadk/runtime/customer/events.py::_display_metadata` 严格原因集合增加这三项；状态仍为 `incomplete`。保留旧三项、精确标识结构、未知拒绝、别名规则和本地身份。

FR-2：保留暂存 final、传输/result ACK 与 cleanup、持久 journal 归属、回放/展示确认及下一轮准入；标识不授予权限、事实、重试或业务成功证明。不改 schema、时限、公开签名或依赖。

FR-3：生产修改前新增同份回归，使用真实 ADK 序列化、事件投影/dispatcher、SQLite journal/重连/历史、展示确认及成功下一轮。覆盖全部六原因、非法/未知标识、partial/工具/thought/user/双别名拒绝和传输失败。既有 Harness 强制 `tests/runtime/customer` 目录执行新增测试。

FR-4：复用已审离线构建流程，从提交后的源码构建独立不可变 wheel 并验证源码/回执/wheel/独立安装包；既有已批准 messages.py PDF overlay 仍在 wheel 外。主审核新制品和业务锁/manifest，不改历史回执或共享 pin。

## 组件影响、任务与验收

Runtime-customer-adk-events CON-8 拥有原因集合，更新成对规范；session-store schema 与状态合同不变。AC-1：原生产拒绝新增原因，旧原因及严格负面对照通过。AC-2：同份测试全部通过，所有标识仍 incomplete，无外网。AC-3：受影响 customer/cleanup 回归、lint/format/diff 和安装验证通过，或准确记录 not_run/blocked。AC-4：交准确提交/父、源码/测试摘要及内部完整源；模板 SDK 源码不是客户包。主/原 owner 在新 Ready 后负责真实页面/API/APM，离线 SDK 绿色不代表功能完成。

## 设计审查与风险

review-spec skill 不可用，已进行等效直接审查：双语一致、原因严格有界、归属/终态/ACK/cleanup/隔离不变、旧原因兼容、真实失效层测试及无外部请求。无阻塞；主明确窄修授权在测试/生产修改前批准此设计。未来未知原因继续拒绝，须另审合同。完整仓库/pre-commit/线上检查可能超出本离线准确任务，不得冒称绿色。

## 验证

红绿及隔离安装证据待本地交付目录记录；执行后补充准确计数与结果。

2026-11-07 实际验证：最终同份145项修前121通过/24失败，修后145全绿；新增测试SHA646a7128043699cd6901b39e6be00eb8437be85e16201a511a94e3f98fe429ea不变。强制customer目录与Runtime cleanup625项全绿、0skip、41本地loopback/0external，源码events SHA08ec92db8329166166e8f4bc098fefcdd5b4a8ad5488199c0d30fc8d92d8137f。改动Python Ruff check/format通过。初次生成fixture收集错误保留并在最终红前纠正，不当机制红。原dev21全部3713源码摘要匹配。独立制品/installed验证接续，完整仓库/pre-commit/真实页面/API/APM未执行，按本轮精确离线范围记录not_run。
