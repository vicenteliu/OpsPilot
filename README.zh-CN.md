# OpsPilot

**AI 增强的 IT 运维工作台 —— 规格驱动、多模型、本地优先**

[![CI](https://github.com/vicenteliu/OpsPilot/actions/workflows/ci.yml/badge.svg)](https://github.com/vicenteliu/OpsPilot/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> English: [README.md](./README.md)
>
> 本文是英文 README 的翻译版本；两者不一致时以英文版为准。

OpsPilot 通过 playbook 驱动的 AI 管线，把原始 IT 工作项（Work item）——事件
（Incident）、服务请求（Service Request）、任务（Task）——转化为结构化、带知识库
引用的摘要。它既可以用 Ollama 完全本地运行，也可以接入各大云端模型；每次运行
都留下可审计的痕迹：内容到达模型之前先做 PII 脱敏，输出经过严格 JSON Schema
校验，每个会话归档一份内容寻址的 artifact 和一条只追加的 trace。

## 项目初衷

AI 正在重塑整个 IT Support 行业。OpsPilot 是对一个具体问题的可运行回答：
**基于当下 LLM 的真实能力，一套实用的 IT Support 工作辅助层应该长什么样？**

- 今天的模型已经足以起草事件摘要、把工作拆解为可派发的任务、找到对的
  runbook——前提是每个结论都有知识库依据、每次运行都可审计。这份依据和
  可审计性正是 OpsPilot 构建的东西。
- 模型能力在持续复利式增长，OpsPilot 的设计是顺着这条曲线走而不是追赶它：
  playbook 锁定模型版本、回归 harness 把关每次升级、规格驱动的契约让换用
  更强的模型只是一次配置变更而非重写。
- 人始终掌握决定权：OpsPilot 只建议严重度、支持线和处置动作；你的工单系统
  和工程师做最终决定。

## 亮点

- **多模型支持** —— Anthropic Claude、OpenAI、OpenRouter、Gemini 或本地
  Ollama；playbook 声明主模型 + 可选备选模型（含本地 Gemma），UI 中按次
  切换，provider 出错时自动降级
- **带引用的知识库检索** —— 向量（LanceDB）+ 全文（SQLite FTS5）混合搜索，
  RRF 融合；强模型走 `tool` 模式（ReAct），弱本地模型走 `prefetch` 注入
- **脱敏优先** —— 任何内容进入模型或知识库之前先剥离 PII
- **可审计会话** —— 内容寻址 artifact、只追加 trace、schema 校验输出、可
  浏览的历史记录
- **沙箱化动作执行** —— AI 提议的 shell 动作在加固 Docker（L2）或 gVisor
  （L3，fail-closed）容器中运行；审批门对危险模式标记要求人工签核
- **复利式 wiki** —— 会话洞见蒸馏为经过 lint 检查、有生命周期管理的 wiki
  页面，沉淀在长期知识库之上
- **MCP 客户端** —— 任意 Model Context Protocol 服务器（stdio/HTTP）的工具
  注入 ReAct 循环，按服务器配置允许/拒绝列表
- **界面与渠道** —— CLI、REPL 终端 UI（Textual，斜杠命令）、多标签
  Web UI（Svelte 5，含知识库增强聊天）、FastAPI 后端；Telegram 渠道把知识库
  问答带进你的聊天软件
- **可观测性** —— Prometheus `/metrics`、OTel 兼容 JSON 日志、`/health`
- **Rust 热路径** —— 分块器（~10×）和分词器（~45×）经 PyO3/maturin 编译，
  纯 Python 透明降级；CI 门槛 ≥5×

## 一览

Web UI —— 暗色优先、侧边栏导航，每个回答都能溯源到知识库：

![OpsPilot web UI](docs/assets/webui.png)

终端 UI —— 同一后端之上的斜杠命令 REPL：

![OpsPilot TUI tour](docs/assets/tui.gif)

## 快速开始

### 前置条件

- Python 3.12+
- [Ollama](https://ollama.com)（本地模型与向量嵌入）
- Node.js 18+ 与 [pnpm](https://pnpm.io)（Web UI 需要）

### 1. 克隆与安装

```bash
git clone https://github.com/vicenteliu/OpsPilot.git
cd OpsPilot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

可选但推荐 —— Rust 扩展（分块/分词提速 ~10–45×；需要
[rustup](https://rustup.rs)）：

```bash
make rust-dev
```

### 2. 拉取模型

```bash
ollama pull nomic-embed-text-v2-moe   # 嵌入模型（必需）
ollama pull gemma4:e4b                 # 本地对话模型（可选 fallback）
```

### 3. 配置

```bash
cp .env.example .env
# 编辑 .env —— 使用云端模型时填入 ANTHROPIC_API_KEY 等。
# 没有云端 key？在 UI 下拉框选择本地 Gemma 模型即可——检索会自动切到
# prefetch 模式，弱模型也能正确引用知识库。
```

### 4. 摄取知识库

```bash
# 仓库自带的英文示例知识库（SOP 与 runbook）：
opspilot ingest examples/sample_data_en/kb/
# 也可以指向你自己的 markdown/PDF/DOCX 文档目录。
```

### 5. 运行

```bash
opspilot tui                              # 终端 UI 工作台
opspilot serve --reload --with-ui         # API + Web UI → http://localhost:5173
```

跑起来之后：在 **Run** 标签提交工单、在 **Chat** 标签向知识库提问，或接入
[Telegram 渠道](docs/channels.md)在手机上与知识库对话。

## 架构

![OpsPilot 系统架构](docs/assets/architecture.png)

![OpsPilot 运行流程](docs/assets/workflow.png)

每次运行：脱敏 → 检索 → 生成 → JSON Schema 校验 → 归档。完整请求流、六层
系统设计、模型路由与检索模式见
[docs/architecture.md](docs/architecture.md)（英文）。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 请求流、分层设计、模型路由、检索模式 |
| [docs/cli.md](docs/cli.md) | TUI、harness、沙箱、MCP、wiki 命令参考 |
| [docs/deployment.md](docs/deployment.md) | Docker Compose、systemd、可观测性、配置 |
| [docs/channels.md](docs/channels.md) | 消息渠道 —— Telegram 应答模式接入指南 |
| [docs/specs/](docs/specs/) | 规格契约：schema + 模板（运行时加载） |
| [docs/adr/](docs/adr/) | 架构决策记录 |
| [docs/zh/design/](docs/zh/design/) | 历史设计文档（中文，不再维护） |
| [ROADMAP.md](ROADMAP.md) | 方向：更多渠道（企微）、移动伴侣、渠道接单 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 开发环境、质量门、PR 约定 |
| [SECURITY.md](SECURITY.md) | 部署模型、威胁模型、漏洞报告 |

## 安全

- OpsPilot 是**单用户**设计；本地使用无需认证，非回环绑定 fail-closed——
  必须配置 bearer token，并在前面加 TLS
  （[ADR-0011](docs/adr/0011-remote-access-bearer-token-proxy-tls.md)、
  [SECURITY.md](SECURITY.md)）
- 脱敏层处理结构化工作项中的 PII，但向任何模型或工具粘贴内容前请务必先
  手动清理
- 云端 API key 一律从环境变量读取 —— 绝不提交入库
- 会话 trace 保存在本地 `~/.opspilot/sessions/`

## 许可证

[MIT](LICENSE)
