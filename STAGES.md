# STAGES — 多语言 / 多界面实施蓝图

> **本文目的**：把 OpsPilot 从"Python + CLI 单后端"升级为**全栈多语言、多界面项目**。覆盖 5 个 stage、4 类 UI、4 种语言、markitdown 集成、macOS 主开发环境约束。
> 与 [ARCHITECTURE.md](ARCHITECTURE.md)（架构总览）+ [IMPLEMENTATION_STAGE_1.md](IMPLEMENTATION_STAGE_1.md)（Stage 1 详细设计）互补。

## TL;DR

- **重新定位**：OpsPilot 不再是单一 CLI 工具，而是一个**多界面工作台**：CLI / TUI / WebUI / GUI 四种入口共享同一组 Python 后端能力
- **语言分工**：Python = 核心后端 / TypeScript = WebUI + Tauri front / Rust = 性能 hot path + Tauri shell / Shell = DevOps
- **markitdown** 作为 ingest 前置层（PDF/DOCX/PPTX/XLSX → markdown），融入 Stage 1 末
- **macOS 主开发**，但所有 production 代码必须 Linux 容器可跑
- **5-Stage 蓝图**：每 stage 加一个界面 + 一类能力；不再一次性铺开
- **不重做** IMPLEMENTATION_STAGE_1.md —— 它仍然是 Stage 1 权威；本文是 Stage 2-5 蓝图 + 跨 stage 的栈与界面约定

---

## 1. 项目重新定位 / Re-positioning

| 维度 | 之前（IMPLEMENTATION_STAGE_1）| 现在（STAGES）|
|---|---|---|
| 入口 | CLI 一种 | CLI + TUI + WebUI + GUI 四种 |
| 后端 | Python 单进程 | Python（FastAPI）服务 + Python lib（CLI/TUI 嵌入）|
| 语言 | Python only | Python + TS + Rust + Shell |
| 用户 | 单人开发者 | 个人 / 团队 / 远程 / 桌面集成 |
| 部署形态 | venv | venv + docker compose + 桌面 .app/.dmg + 单文件 binary |
| 核心约束 | 不变 | 同 ARCHITECTURE.md 强约束（PII 红线 / 版本锁定 / 可重算） |

**核心保持不变**：spec 阶段的 7 目录契约、20 个 schema、48 个模板、4 份 e2e 样例都是**多语言共享的"事实来源"**。任何语言的实现都从这里读 schema、对齐字段。

### 1.2 用户决策记录（2026-05-01）/ Decision log

本节固化用户对 4 个 open question 的答复，作为后续 stage 取舍依据：

| # | Question | 决定 | 影响 |
|---|---|---|---|
| 1 | markitdown 是否启用 image LLM vision 描述？ | **关闭** | Stage 1 不引入 vision provider；图片在 markitdown 输出中保留为占位（alt text / placeholder）；future stage 视需求开 |
| 2 | 前端框架 Svelte vs Vue vs React？ | **Svelte** | Stage 2 起锁定 Svelte 5 + SvelteKit；不再讨论 |
| 3 | GUI（Tauri 桌面）优先级？ | **推到 Stage 5 + 标 optional**；**条件**：若 WebUI 体验足够好，GUI 可以**不开发** | Stage 4 移除 GUI；Stage 5 GUI 是"如果需要才做"；CLI / TUI / WebUI 才是必做三 UI |
| 4 | Rust 引入时机？ | **保守，Stage 3 才引入** | Stage 1-2 纯 Python + TS；Stage 3 才出现 PyO3/maturin/Cargo |

直接结果：**Stage 顺序与内容下面 §7 已据此调整**。

---

## 2. 多语言栈分工 / Multi-language stack

### 2.1 Python — 核心后端

**做什么**：
- 几乎所有"业务逻辑" capability：providers / memory / session / sandbox / harness / skills / wiki
- FastAPI HTTP 服务（Stage 2 起）暴露给 WebUI / GUI
- Textual TUI 直接嵌入 Python lib（同进程）
- Typer CLI 直接调用 Python lib

**不做**：
- 性能 hot path（chunker、tokenizer、markdown parser 解析）—— 用 Rust 加速并通过 PyO3 暴露
- 桌面 GUI shell —— 用 Tauri (Rust)

**版本**：3.12（与 Stage 1 一致）

### 2.2 TypeScript — 前端

**做什么**：
- WebUI 单页应用（Stage 2）
- 同一份代码也作为 Tauri 桌面应用的 webview 内容（Stage 4）
- 可能：浏览器扩展（远期；用于"clip web → ingest"工作流）

**框架**：**Svelte 5 + SvelteKit**（推荐）
- 理由：编译时框架，包小、reactive 简洁；与 OpsPilot 的"轻量 + 可读"风格匹配
- 备选：Vue 3 + Vite（生态更熟）/ React + Next.js（生态最大但 verbose）
- **不选** Angular（过重）

**配套**：
- 状态：Svelte stores（默认）；复杂状态用 [TanStack Query](https://tanstack.com/query) 管 server state
- UI 组件：[shadcn-svelte](https://www.shadcn-svelte.com/) 或 [Skeleton](https://www.skeleton.dev/)
- 图表：Echarts 或 Apache vega-lite（用于 harness 报告 / iteration 历史）

### 2.3 Rust — 性能 hot path + Tauri shell

**做什么**：
- **PyO3 bindings**（Stage 3）：把性能敏感模块用 Rust 重写并暴露给 Python
  - markdown chunker（headings_then_size）
  - tiktoken 风格的 tokenizer
  - sha256 / ULID 工具（其实 Python 够用，但配合 LanceDB 大批量场景值得）
- **Tauri 2 桌面 shell**（Stage 4）：用 Rust 调系统 WebView，加载 §2.2 的同一份前端
- **未来**：独立 CLI binary（去 Python 依赖；嵌入式部署）

**Cargo workspace**：
```
crates/
├── opspilot-core/        # 共享类型、ID、schema 校验（Rust 侧）
├── opspilot-chunker/     # PyO3 bindings: markdown chunker
├── opspilot-tokenizer/   # PyO3 bindings: tokenizer
└── opspilot-tauri/       # Tauri 桌面应用（main + commands）
```

**Toolchain**：
- `rustc` ≥ 1.79（macOS Apple Silicon + x86_64）
- `cargo` + `maturin`（Python wheel 构建）

**避免一次性 Rust 化**：Stage 1-2 不写 Rust。Stage 3 才引入，且必须证明 Python 实现已是瓶颈。

### 2.4 Shell / Bash — DevOps

**做什么**：
- `Makefile` 顶层入口（已规划）
- `scripts/` 下的脚本：
  - `scripts/install-macos.sh` —— Homebrew 装 deps
  - `scripts/install-linux.sh` —— apt 装 deps
  - `scripts/preflight.sh` —— 检测 Docker / Ollama / Python / Rust toolchain 就绪
  - `scripts/release.sh` —— 打 tag、build wheel、build Tauri、build docker
  - `scripts/golden-run.sh` —— 端到端跑 examples/
- CI 钩子（GitHub Actions YAML 内嵌）
- pre-commit hooks

**约束**：
- shellcheck 必过
- POSIX 兼容（不假设 bash 4+ 功能；macOS 默认 bash 是 3.2）—— **这是 macOS 主开发的硬约束**
- 复杂逻辑改用 Python script，shell 只做 orchestration

---

## 3. Markitdown 集成 / Markitdown integration

### 3.1 是什么

[Markitdown](https://github.com/microsoft/markitdown) —— 微软开源的 Python 库（信息日期 2026-05-01；使用前核验）。把多种文档格式转成 markdown：
- PDF / DOCX / PPTX / XLSX
- HTML / EPUB / RTF
- 图片（OCR / LLM vision，可选）
- 音频（whisper，可选）
- ZIP（递归解压）

### 3.2 在 OpsPilot 中的位置

```
raw file (任意格式)
   │
   ▼  ★ markitdown adapter ★（新增）
markdown
   │
   ▼  现有 memory.ingestion (redact → chunk → embed → upsert)
KB document + chunks + vectors
   │
   ▼  wiki.ingest（Stage 3 起）
wiki page
```

**关键决定**：markitdown 不替代现有 ingestion，**只在前面加一层**。markdown 输入仍直走 ingestion（不变）。

### 3.3 实施位置（Stage 1 末或 Stage 2 初）

新增 `src/opspilot/memory/markitdown_adapter.py`：

```python
def to_markdown(path: Path, *, llm_for_images: ProviderProtocol | None = None) -> str:
    """Convert any supported file to markdown.
    Detects format by extension + magic bytes.
    For images, optionally route through provider for description (vision).
    For .md/.markdown, passes through unchanged."""

def supports(path: Path) -> bool: ...
```

CLI 自动调度：

```bash
# Stage 1 末：
opspilot ingest sop_vpn.pdf      # → markitdown 转 md → ingestion 流水线
opspilot ingest meeting.docx     # 同上
opspilot ingest sop_vpn.md       # 直走（无 markitdown）
```

**集成放在 IMPLEMENTATION_STAGE_1 的 PR-5 内**（Ingestion pipeline）：在 `ingestion.py` 的 `discover` 阶段后、`redact` 阶段前调 `markitdown_adapter.to_markdown()` 把非 md 文件统一为 md。

### 3.4 强约束

- markitdown 输出的 markdown 也必须**走 redaction**（同 redaction-rules.yaml）
- PDF 解析失败要 hard fail（不假装成功 + 空白 markdown）
- 图片 vision 描述功能 **Stage 1 关闭**（避免引入 vision provider 依赖）
- 转换前后保留**原始文件路径与 sha256**到 `kb-document.extensions.markitdown` 字段，便于审计与回溯

---

## 4. macOS 主开发环境 / macOS as primary dev OS

### 4.1 已知坑（必须前期处理）

| 坑 | 影响 | 解决 |
|---|---|---|
| macOS 默认 bash = 3.2 | 现代 shell 语法（关联数组、`mapfile` 等）不可用 | shell 限 POSIX；高级用 Python |
| BSD coreutils（`sed -i ''` vs GNU `sed -i`）| Makefile 跨平台失败 | 用 Python 替代 sed/awk；或 `brew install gnu-sed coreutils` |
| Apple Silicon (arm64) vs x86_64 | LanceDB / pyarrow 二进制 wheel 可能不全 | 用最新版（已支持）；本地构建用 `MAKEFLAGS=-j$(sysctl -n hw.ncpu)` |
| Docker Desktop 资源默认 2GB | LanceDB 大批量索引 OOM | `~/.docker/config.json` 调到 8GB+ |
| 文件系统大小写不敏感 | 引用 `Sop.md` 与 `sop.md` 都能命中 | CI 跑 Linux 严格大小写检查 |
| Gatekeeper / 签名 | 自建 Tauri app 默认拒签 | 开发用 `xattr -d com.apple.quarantine`；分发要 Apple Developer ID |
| 中文输入法相关 | TUI 在某些 IDE 终端切换中文有 escape sequence 问题 | 推荐 iTerm2 + 系统终端备选 |

### 4.2 推荐主开发栈

```bash
# 一行装齐（macOS）
brew install python@3.12 node@22 rustup-init pnpm pyenv direnv \
             gnu-sed coreutils shellcheck sqlite3 just \
             docker docker-compose lima
rustup-init -y
```

- `python@3.12`：核心后端
- `node@22 + pnpm`：TypeScript 前端
- `rustup`：Rust toolchain（Stage 3+）
- `pyenv`：管理多版本 Python（CI 跑 3.12 / 3.13 兼容）
- `direnv`：自动加载 `.envrc`（Ollama 端口、API key 占位）
- `gnu-sed coreutils`：跨平台 shell 一致性
- `shellcheck`：所有 .sh 必过
- `lima`：可选；macOS 上跑 Linux VM（用于 sandbox L3+ 测试）

### 4.3 开发流（建议）

```
本机 macOS                          docker-compose
├── venv（Python lib + CLI）         ├── ollama（LLM）
├── pnpm dev（前端 hot reload）      └── lancedb（如远端模式；Stage 1 用 embedded）
├── pytest（短测）
└── Tauri dev（GUI hot reload，Stage 4）
                                    
CI（GitHub Actions, Linux）
├── 全测试矩阵（py 3.12 + 3.13）
├── golden test（real Ollama）
└── docker build + Tauri build matrix
```

---

## 5. 多界面策略 / Multi-UI surfaces

| 界面 | 谁用 | 主要场景 | 技术 | 引入 stage |
|---|---|---|---|---|
| **CLI** | 开发者 / CI / shell 集成 | scriptable; ingest 单文件; harness regression | Python + Typer | Stage 1 |
| **TUI** | 终端原住民 / SSH 远程 | 浏览 sessions / 手动驱动一次 ingest / 看 harness 报告 | Python + Textual | Stage 3 |
| **WebUI** | 团队协作 / 跨设备 | 提交工单 / 看 wiki / 审 lint issues / 仪表板 | Svelte + FastAPI | Stage 2 |
| **GUI** | 桌面深度集成 | 拖拽文件入 ingest / 系统通知 / 离线优先 | Tauri (Rust) + Svelte（复用 WebUI 代码） | Stage 4 |

### 5.1 共享原则

- **后端唯一**：4 个界面**共用同一组 Python lib + FastAPI 服务**；无重复实现
- **数据契约一致**：4 个界面看到的"session / page / skill / fixture"形态完全相同
- **CLI 是合约**：所有 WebUI/TUI/GUI 能做的事，CLI 都能做（CLI 是 backend API 的最小投影）

### 5.2 路由

```
        ┌────────────────────────────────────────────────┐
        │   FastAPI HTTP server  (Stage 2 起)            │
        │   /api/v1/{ingest, sessions, kb, harness, ...} │
        └──────────────┬─────────────┬───────────────────┘
                       │             │
            ┌──────────┘             └──────────┐
            ▼ HTTP                              ▼ HTTP
       ┌──────────┐                        ┌──────────┐
       │  WebUI   │                        │   GUI    │
       │ (browser)│                        │ (Tauri)  │
       └──────────┘                        └──────────┘

            ┌────────────────────────────────────────────┐
            │ python -m opspilot import & in-process     │
            └──────────────┬─────────────┬───────────────┘
                           │             │
                ┌──────────┘             └─────────┐
                ▼                                  ▼
            ┌──────┐                          ┌──────┐
            │ CLI  │                          │ TUI  │
            └──────┘                          └──────┘
```

CLI/TUI 直接 import Python lib（无 HTTP 开销）；WebUI/GUI 走 HTTP（因为是不同进程 / 跨设备）。

---

## 6. Mono-repo 目录结构 / Repo layout

```
OpsPilot/
├── README.md                         (existing)
├── ARCHITECTURE.md                   (existing)
├── CLAUDE.md                         (existing)
├── IMPLEMENTATION_STAGE_1.md         (existing - Stage 1 详细)
├── STAGES.md                         (本文 - 多语言/多界面 + Stage 2-5)
│
├── pyproject.toml                    (Stage 1, PR-1)
├── Cargo.toml                        (Stage 3 引入 - workspace root)
├── package.json                      (Stage 2 引入 - workspace root)
├── pnpm-workspace.yaml               (Stage 2)
├── Makefile                          (Stage 1)
├── docker-compose.yml                (Stage 1, PR-3)
├── .python-version                   (Stage 1)
├── .nvmrc                            (Stage 2)
├── .env.example                      (Stage 1)
├── .envrc                            (Stage 1)
│
├── src/opspilot/                     ← Python（IMPLEMENTATION_STAGE_1.md §1）
│   ├── ...
│   ├── server/                       (Stage 2 引入) FastAPI
│   │   ├── main.py
│   │   ├── routes/{ingest,sessions,kb,harness,wiki,skills}.py
│   │   ├── auth.py
│   │   └── deps.py
│   └── tui/                          (Stage 3 引入) Textual
│       ├── app.py
│       └── screens/...
│
├── crates/                           ← Rust workspace（Stage 3 引入）
│   ├── opspilot-core/
│   ├── opspilot-chunker/             (PyO3 bindings)
│   ├── opspilot-tokenizer/           (PyO3 bindings)
│   └── opspilot-tauri/               (Stage 4) 桌面 shell
│
├── frontend/                         ← TypeScript（Stage 2 引入）
│   ├── package.json
│   ├── apps/
│   │   ├── web/                      Svelte SPA → 浏览器
│   │   └── desktop/                  (Stage 4) 复用 web 但打包到 Tauri
│   ├── packages/
│   │   ├── ui/                       共享组件
│   │   └── api-client/               OpenAPI 自动生成的 TS client
│   └── pnpm-workspace.yaml
│
├── scripts/                          ← Shell/Bash
│   ├── install-macos.sh
│   ├── install-linux.sh
│   ├── preflight.sh
│   ├── release.sh
│   └── golden-run.sh
│
├── docker/                           ← Docker assets
│   ├── ollama.Dockerfile
│   ├── opspilot-server.Dockerfile    (Stage 2)
│   └── compose.dev.yml
│
├── ci/                               ← GitHub Actions
│   ├── lint.yml
│   ├── test.yml
│   ├── golden.yml
│   ├── build-tauri.yml               (Stage 4)
│   └── release.yml
│
├── tests/                            ← Python tests（IMPLEMENTATION_STAGE_1.md §6）
├── tests-frontend/                   (Stage 2) Vitest + Playwright
├── tests-rust/                       (Stage 3) cargo test
│
└── (existing spec dirs:
    prompts/, playbooks/, demos/, governance/, case-studies/,
    providers/, memory/, session/, sandbox/, harness/, skills/, wiki/, examples/)
```

---

## 7. 5-Stage 蓝图（capability × language × UI 矩阵）/ 5-stage blueprint

| Stage | 时长 | 核心 capability 增量 | 新增语言 | 新增 UI | 关键依赖（新）|
|---|---|---|---|---|---|
| **1** | 1.5–2w | providers (Ollama) + memory + session + harness + orchestrator (1 playbook) + **markitdown**（vision OFF） | Python | CLI | typer / pydantic / lancedb / sqlite + fts5 / httpx / **markitdown** |
| **2** | 2w | + skills 框架 + 第二 provider (Anthropic) + REST API | + TS / **Svelte** | + WebUI | fastapi / uvicorn / svelte / vite / pnpm / shadcn-svelte / openapi-ts |
| **3** | 2–3w | + wiki ingest + 长期 KB 全功能 + Rust hot path | + **Rust (PyO3)** | + TUI (Textual) | textual / cargo / maturin / pyo3 |
| **4** | 2w | + iteration + feedback loop + wiki lint + 第二批 provider（OpenRouter / OpenAI） | — | — | （只新增 capability，不新栈/新 UI） |
| **5** | open | + 剩余 provider (Gemini / Grok) + sandbox L2/L3 + MCP integration + 部署；**GUI (Tauri) 可选** | + Rust (Tauri) **可选** | + **GUI 可选** | docker SDK / mcp client / tauri 2 / k8s（视需求）|

> **GUI 条件性决定**：Stage 5 的 GUI（Tauri）**只有在 Stage 2 完成后 WebUI 体验不足以满足桌面集成需求时才启动**。如果 WebUI 体验好，GUI 不开发——节省 ~2 周 + 跨平台分发成本。决定时机：Stage 4 末做 WebUI vs GUI 评审。

### 7.1 Stage 1 — Python core + CLI + markitdown（详细见 [IMPLEMENTATION_STAGE_1.md](IMPLEMENTATION_STAGE_1.md)）

**唯一调整**：在 PR-5（Ingestion pipeline）中加 markitdown adapter。其他 7 个 PR 不变。

退出标准（与 IMPLEMENTATION_STAGE_1.md §9 一致）：
- 所有 examples/ 通过 schema 校验
- `make golden` 通过：`opspilot run` 输出结构等价、RAG 三件套全过、judge ≥ 0.85
- **新增**：`opspilot ingest sample.pdf` 能跑通（markitdown 转 md → 走 ingestion）

### 7.2 Stage 2 — FastAPI 后端 + Svelte WebUI + 第二 provider

**新增能力**：
- skill 框架最小实现（registry + 1 个 SKILL.md 加载）；**iteration 留 Stage 4**
- providers/anthropic.py（Claude API；`x-api-key` + `anthropic-version` header）
- FastAPI server 暴露：`/ingest`（文件上传）/ `/sessions/{id}` / `/kb/search` / `/harness/run`
- Svelte SPA：5 个页面（Dashboard / Ingest / Sessions / KB / Harness）
- OpenAPI 自动生成 TS client（`openapi-typescript-codegen`）
- 简单 auth：本地 token / 单用户

**新增 PR（在 Stage 1 8 个 PR 之后）**：
- PR-9 / fastapi-server：API skeleton + 4 个 route + auth
- PR-10 / svelte-skeleton：Vite + Svelte + shadcn-svelte 选型 + OpenAPI client
- PR-11 / web-ingest+sessions：文件上传 + session 列表
- PR-12 / web-kb-search：KB 检索界面 + retrieval response 可视化
- PR-13 / web-harness：跑 harness + 看 results.jsonl 报告
- PR-14 / providers-anthropic：第二 provider + provider switching
- PR-15 / skills-minimal：skill registry 加载 + SKILL.md 解析（不含 distillation/iteration）

**退出标准**：
- WebUI 能完成 Stage 1 CLI 全部操作
- Anthropic provider 能跑 golden test，分数与 Ollama 在同 fixture 上 delta < 0.1
- API 文档 (OpenAPI) 自动生成且 type-safe（前端调用错的话编译失败）

### 7.3 Stage 3 — Rust hot path + TUI + wiki ingest

**新增能力**：
- wiki/ ingest 全实现（query→page 留 Stage 4；lint 留 Stage 4）
- memory long-term 全功能（rerank、incremental sync、namespace）
- TUI（Textual）：8 屏 - dashboard / sessions / kb-browser / wiki-tree / harness / lint-issues / providers-status / config

**Rust hot path 引入**：
- `crates/opspilot-chunker`：markdown chunker（性能 5-10x Python）
- `crates/opspilot-tokenizer`：BPE-ish tokenizer
- `maturin develop` 注入到 Python venv

**新增 PR**：
- PR-16 / rust-workspace：Cargo workspace + maturin 构建链路
- PR-17 / rust-chunker：Rust chunker + Python wrapper + 新 benchmarks（必须 ≥ 5x Python）
- PR-18 / rust-tokenizer：同上
- PR-19 / wiki-ingest：wiki/ingest 实现 + index/log 维护
- PR-20 / textual-tui-skeleton：Textual app shell + screen 路由
- PR-21 / textual-screens：8 个 screen 实装

**退出标准**：
- Rust chunker benchmark ≥ 5x Python 实现
- TUI 能完成 95% CLI 操作；Plus 看 wiki tree（CLI 没有）
- 第三个 e2e 样例（wiki ingest）跑得过

### 7.4 Stage 4 — iteration + wiki lint + 第二批 provider（**无新 UI / 无新语言**）

> 用户决策 #3：GUI 推到 Stage 5；本 stage 专注后端能力 + 用现有三 UI（CLI / TUI / WebUI）暴露。

**新增能力**：
- `skills/iteration` 全实现（feedback collector + iteration runner + lineage + variant 管理）
- `wiki/lint` + `wiki/query→page`（compounding insight loop）
- 第二批 provider：**OpenRouter** + **OpenAI** （Gemini / Grok 推到 Stage 5；先把 OpenRouter 做出来作"一把 key 接百家"的降级链）
- WebUI 加 iteration 仪表板 + lint issues 列表 + lineage 可视化（复用 Stage 2 的 Svelte 代码）
- TUI 加同等屏幕（复用 Stage 3 的 Textual）

**新增 PR**：
- PR-22 / iteration-engine（Python）
- PR-23 / wiki-lint（Python；10 类 issue 检测器）
- PR-24 / wiki-query-to-page
- PR-25 / providers-openrouter
- PR-26 / providers-openai
- PR-27 / web-iteration-dashboard（Svelte）
- PR-28 / tui-iteration-screens（Textual）

**退出标准**：
- ✅ 第四个 e2e 样例（`examples/itr_ticket_summary_zh_v1_3_0/`）跑得过：feedback signals → trigger → variants → eval → promote 全链路
- ✅ WebUI 能完整看到 iteration 历史 + lineage 树
- ✅ OpenRouter 能跑 golden test，与 Anthropic / Ollama 在同 fixture 上 delta < 0.1（实测 0.983，delta=0.015）
- ✅ Stage 4 末做 **WebUI vs GUI 评审**：**保留 WebUI，不做 Tauri GUI**（见 ADR-0004）

**Stage 4 已完成（2026-05-07）**

### 7.5 Stage 5 — 生产化（GUI 已排除）

> 用户决策 #4（Stage 4 末评审）：WebUI 体验已满足需求，**Tauri GUI 永久排除**，Stage 5 不再包含任何 GUI 工作。

**核心生产化（必做）**：
- 剩余 provider：**Gemini API** + **Grok API**（Stage 4 已含 OpenRouter + OpenAI；至此 6 provider 齐全）
- sandbox L2（hardened Docker：seccomp + AppArmor + cap-drop + RO rootfs）
- sandbox L3（gVisor / Firecracker / Kata 之一；视需求）
- MCP client（fs-readonly / git-readonly / Notion / Slack 等；与 mcp-config schema 对齐）
- Linux 服务器部署：systemd unit + docker-compose prod + 可选 Helm chart
- 监控接入：Prometheus metrics + 结构化日志（OTel 兼容）
- macOS 桌面 packaging（CLI binary + GUI 如启动）

**条件性（仅 Stage 4 末评审通过才做）**：
- **GUI（Tauri 2）**：复用 Stage 2 的 Svelte 代码 + Rust 系统集成（文件拖拽 / 系统通知 / 文件关联 / 系统托盘）
  - 触发条件示例（Stage 4 末判断）：
    - WebUI 在跨设备 / 离线场景体验不足（如内网无 server）
    - 用户需要原生集成（macOS Spotlight / Finder 右键菜单等）
    - 团队接受多 OS 分发与签名复杂度
  - 不触发示例：WebUI + 浏览器扩展（如 Obsidian Web Clipper）已足够

**条件性 PR（GUI 启动时）**：
- PR-G1 / tauri-shell：Tauri 2 项目 skeleton + 复用 frontend/web
- PR-G2 / tauri-system-integration：file drag-drop / system tray / 自动更新
- PR-G3 / tauri-build-matrix：macOS .app + Linux .AppImage + .deb

**退出标准（必做部分）**：
- `make harness` 在 6 个 provider 上分别跑通
- sandbox L2 在生产环境跑过 1 个月无逃逸事件
- ✅ MCP integration：fs-readonly（2 tools）+ Notion（22 tools）端到端跑通（2026-05-07）

---

## 8. 跨 stage 不变量 / Cross-stage invariants

无论 stage 多少，以下永远成立：

1. **Spec 是真相之源**：7 个目录的 schema/template 是所有语言/界面读的同一份；不允许在某语言里"重新定义"
2. **PII 红线**：不论是 markitdown 输出、HTTP API 响应、GUI 显示，都要先经 redaction
3. **版本锁定**：`model_ref` / `embedding_model` / skill `version` / wiki page `version` 全禁 `latest`/`auto`/`stable`
4. **可重算决策**：iteration 决策、harness 评分、wiki lint —— 给定输入应能机械重算结果
5. **CLI 是合约**：每个 capability 必须先在 CLI 可用（哪怕粗糙），再进 WebUI/TUI/GUI
6. **macOS dev / Linux prod**：CI 必须包含 Linux 矩阵；macOS-only 的依赖（Apple SDK）禁出现在 production 代码
7. **审计 append-only**：session.audit / wiki.log / lineage 都不允许重写历史
8. **不引入 langchain / autogen**：架构已自洽，引入会破坏 schema 主导
9. **测试要 e2e**：每个 stage 退出标准都包含一个新的 e2e 样例跑通
10. **跨语言传输 = JSON + schema**：Python ↔ TS ↔ Rust 之间不传二进制；都用 schema 约定的 JSON

---

## 9. 技术栈选型决策 / Stack decision log

| 维度 | 选 | 不选 | 决策理由 |
|---|---|---|---|
| 后端语言 | Python 3.12 | Go / Rust | LLM 生态 / Pydantic / FastAPI 成熟；Rust 用于 hot path 而非主体 |
| 前端框架 | **Svelte 5 + SvelteKit** | React / Vue / Solid | 编译时框架，包小、reactive 简洁；与"轻量 + 可读"风格一致 |
| 桌面 GUI | **Tauri 2** | Electron | 包小（10 MB vs 80+ MB），原生 WebView，与 Rust 子项目共栈 |
| TUI | **Textual** | Ratatui (Rust) / Bubbletea (Go) | Python 原生，与后端共栈，开发速度优先 |
| CLI | **Typer** | Click / argparse | Pydantic 集成，自动生成 help，类型友好 |
| 验证 | **jsonschema (Python)** | pydantic only | jsonschema 是跨语言标准；TS/Rust 也可读同一份 schema |
| 向量库 | **LanceDB** | Chroma / Qdrant / pgvector | embedded、列式、增量、git-friendly 文件布局 |
| 关键字索引 | **SQLite + FTS5** | Postgres / Elasticsearch | embedded、零运维 |
| HTTP server | **FastAPI** | Litestar / Flask | OpenAPI 自动生成，async 默认，Pydantic 集成 |
| Provider 抽象 | 自实现（按 schema）| LiteLLM | LiteLLM 抽象漏（Anthropic 工具调用细节磨平）|
| Markdown 解析 | Stage 1: 手撸正则；Stage 3: Rust comrak | markdown-it-py | 性能 + 与 chunker 紧耦合 |
| 文档转 markdown | **markitdown** | pandoc / unstructured.io | 微软维护、专为 LLM 场景、active 开发 |
| Python build | hatch / setuptools | poetry | 轻量；不与 maturin 冲突 |
| Rust + Python bridge | **maturin + PyO3** | cffi / cython | 现代标准 |
| Frontend build | **Vite** | Webpack / Turbopack | 极快 dev、Svelte 默认 |
| Mono-repo（前端）| **pnpm workspaces** | nx / turborepo / lerna | 简单够用 |
| CI | **GitHub Actions** | GitLab CI / CircleCI | 默认；社区 actions 多 |
| 桌面打包 | Tauri build | electron-builder | 见上 GUI 选型 |
| 中文分词（FTS5）| Stage 1: ngram(2,3)；Stage 3: 评估 jieba | unicode61 only | 中文召回必须 |

---

## 10. 现在的开发起点 / Where to start now

按 ARCHITECTURE.md → IMPLEMENTATION_STAGE_1.md → STAGES.md 这三层文档，开发起点：

1. **第一行代码**仍是 `src/opspilot/ids.py`（IMPLEMENTATION_STAGE_1.md PR-1）—— 不变
2. PR-5 增加 `memory/markitdown_adapter.py`（本文 §3.3）—— 新增
3. Stage 1 完成后才开 Stage 2 PR-9 起的 FastAPI / Svelte 工作

**最小验证回路**（你能在今天跑通）：

```bash
# 装齐 macOS 环境
bash scripts/install-macos.sh    # 待写；目前手动等价：
brew install python@3.12 sqlite3 docker
pyenv install 3.12 && pyenv local 3.12

# 装 ollama
brew install ollama
ollama serve &
ollama pull qwen2.5:14b-instruct
ollama pull nomic-embed-text

# clone & install
git clone <repo>
cd OpsPilot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # 这一步 pyproject.toml 是 PR-1 写

# 跑 PR-1 退出标准
make validate                     # 21 个 schema 全过
make test                         # 单测全过
```

---

## 11. 提交建议 / Commit suggestion

```bash
cd ~/Workspace/OpsPilot && \
git add STAGES.md && \
git commit -m "docs: add multi-stack / multi-UI implementation plan (STAGES.md)

Re-position OpsPilot from a single-CLI tool to a multi-surface workbench:
4 UIs (CLI / TUI / WebUI / GUI), 4 languages (Python / TS / Rust / Shell),
markitdown as ingest front-layer, macOS as primary dev OS.

Key decisions:
- Python core unchanged (Stage 1 still Python-only + CLI)
- Stage 2: FastAPI server + Svelte WebUI + 2nd provider (Anthropic)
- Stage 3: Rust hot path (PyO3 chunker/tokenizer) + Textual TUI
           + wiki ingest
- Stage 4: Tauri 2 desktop GUI + iteration engine + wiki lint
- Stage 5: production hardening + remaining providers + MCP

Stack rationale:
- Svelte 5 over React (compile-time, smaller bundle)
- Tauri 2 over Electron (10MB vs 80MB+, native WebView)
- Textual TUI (Python, shared lib with backend)
- maturin + PyO3 for Rust↔Python bridge
- markitdown for PDF/DOCX/PPTX ingest

Cross-stage invariants documented (10 rules); macOS dev pitfalls
(bash 3.2, BSD coreutils, Docker resource caps) explicitly handled.

Companion to:
- ARCHITECTURE.md (architectural overview)
- IMPLEMENTATION_STAGE_1.md (Stage 1 detailed design — unchanged
  except markitdown added to PR-5)" && \
git push origin main
```

---

## 12. 文档导航 / Doc navigation

到此 4 份核心文档形成完整阅读路径：

| 文档 | 谁读 | 何时读 |
|---|---|---|
| [README.md](README.md) | 所有人 | 第一次接触项目 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 评审 / 新成员 / 自己复盘 | 想看"系统长什么样" |
| [STAGES.md](STAGES.md)（本文）| 实施前 / 加新 stage 时 | 想看"分几步走 + 用什么栈" |
| [IMPLEMENTATION_STAGE_1.md](IMPLEMENTATION_STAGE_1.md) | 实施 Stage 1 时 | 想看"这周写什么代码" |
| 各目录 SPEC.md | 改 schema / 加字段时 | 想查"具体字段含义" |
| [CLAUDE.md](CLAUDE.md) | 任何代码改动前 | 行为约定（4 条原则）|

---

## 一句话收尾

**OpsPilot = Python 核心 + TS 前端 + Rust 加速 + Shell 胶水，跨 4 类界面共享同一组 spec 契约。markitdown 让任何文件都能进 KB；macOS 主开发，Linux production。Stage 1 不变，Stage 2-5 沿四语言四界面的轴展开。**
