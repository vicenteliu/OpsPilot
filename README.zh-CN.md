# OpsPilot

**AI 增强的 IT 运维工作台 —— 规格驱动、多模型、本地优先**

> English: [README.md](./README.md)
>
> 本文是英文 README 的翻译版本；两者不一致时以英文版为准。

OpsPilot 通过 playbook 驱动的 AI 管线，把原始 IT 工作项（Work item）——事件
（Incident）、服务请求（Service Request）、任务（Task）——转化为结构化、带知识库
引用的摘要。它既可以用 Ollama 完全本地运行，也可以接入各大云端模型；每次运行
都留下可审计的痕迹：内容到达模型之前先做 PII 脱敏，输出经过严格 JSON Schema
校验，每个会话归档一份内容寻址的 artifact 和一条只追加的 trace。

## 亮点

- **多模型支持** —— Anthropic Claude、OpenAI、OpenRouter、Gemini 或本地
  Ollama；UI 中按次切换；playbook 声明主模型 + 本地 fallback（如 Claude → Gemma）
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
- **四种界面** —— CLI、8 模块终端 UI（Textual）、多标签 Web UI（Svelte 5，
  含知识库增强聊天）、FastAPI 后端
- **可观测性** —— Prometheus `/metrics`、OTel 兼容 JSON 日志、`/health`
- **Rust 热路径** —— 分块器（9.6×）和分词器（45×）经 PyO3/maturin 编译，
  纯 Python 透明降级

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

可选但推荐 —— Rust 扩展（分块/分词提速 10–48×；需要
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
# 编辑 .env —— 使用云端模型时填入 ANTHROPIC_API_KEY 等
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

## 架构

```
Browser (Svelte 5)          opspilot tui / CLI
        └──────────────┬──────────────┘
                       ▼
              FastAPI (opspilot.api)
                       ▼
                 Orchestrator
   ┌───────────┬───────┴───────┬─────────────┐
   ▼           ▼               ▼             ▼
Redactor   KB Search       Provider     SessionManager
(PII 脱敏) (FTS5+向量      (Claude ·    (trace + artifact
            混合, RRF)      OpenAI ·     归档)
                            Gemini ·
                            Ollama)
```

每次运行：脱敏 → 检索 → 生成 → JSON Schema 校验 → 归档。完整请求流、六层
系统设计、模型路由与检索模式见
[docs/architecture.md](docs/architecture.md)（英文）。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 请求流、分层设计、模型路由、检索模式 |
| [docs/cli.md](docs/cli.md) | TUI、harness、沙箱、MCP、wiki 命令参考 |
| [docs/deployment.md](docs/deployment.md) | Docker Compose、systemd、可观测性、配置 |
| [docs/specs/](docs/specs/) | 规格契约：schema + 模板（运行时加载） |
| [docs/adr/](docs/adr/) | 架构决策记录 |
| [docs/zh/design/](docs/zh/design/) | 历史设计文档（中文，不再维护） |
| [ROADMAP.md](ROADMAP.md) | 方向：远程访问基座、Channel、移动伴侣 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 开发环境、质量门、PR 约定 |
| [SECURITY.md](SECURITY.md) | 部署模型、威胁模型、漏洞报告 |

## 安全

- OpsPilot 目前是**单用户、仅本地**设计 —— 不要把 API 暴露到公网
  （[ADR-0002](docs/adr/0002-stage2-single-user-no-auth.md)、
  [SECURITY.md](SECURITY.md)）
- 脱敏层处理结构化工作项中的 PII，但向任何模型或工具粘贴内容前请务必先
  手动清理
- 云端 API key 一律从环境变量读取 —— 绝不提交入库
- 会话 trace 保存在本地 `~/.opspilot/sessions/`

## 许可证

MIT
