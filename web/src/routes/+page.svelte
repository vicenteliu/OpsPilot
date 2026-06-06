<script lang="ts">
  import '../app.css';
  import {
    getConfig, getModels, runTicketStream, listSessions, getSession, getLineage,
    getKBStats, listKBDocs, searchKB, wikiIngest, wikiQueryToPage, wikiLint, wikiPromote, listMCPServers,
    listConflicts, resolveConflict, correctChunk, listCorrections, generateVendorDocStream,
    listWikiPages, listVendorDocs, getWikiPage, getVendorDoc, chatStream,
    type RunResponse, type TicketSummary, type NextAction, type Task, type SessionSummary, type ModelOption, type SkillLineage,
    type KBDoc, type KBHit, type KBConflict, type KBStats, type KBCorrection, type WikiLintIssue, type MCPServer,
    type VendorDoc, type VendorDocSection, type WikiPageSummary, type VendorDocSummary, type WikiPageDetail,
    type ChatMessage,
  } from '$lib/api';

  // --- Theme ---
  let theme = $state<'light' | 'dark'>(
    typeof localStorage !== 'undefined'
      ? (localStorage.getItem('theme') as 'light' | 'dark') ?? 'light'
      : 'light'
  );

  $effect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  });

  function toggleTheme() {
    theme = theme === 'dark' ? 'light' : 'dark';
  }

  // --- Active Tab ---
  type Tab = 'run' | 'kb' | 'wiki' | 'vendordoc' | 'mcp' | 'iteration' | 'chat' | 'guide';
  let activeTab = $state<Tab>('run');

  // --- Guide Tab interactive state ---
  type GuideKey = 'zh' | 'en';
  let guideLang  = $state<GuideKey>('zh');
  let selectedArch = $state<string | null>(null);
  let selectedStep = $state<number | null>(null);
  let expandedFeat = $state<string | null>(null);

  type ArchItem = { name: string; tech?: string; desc: string };
  type Section  = { title: string; desc: string; items: ArchItem[] };
  type WfItem   = { name: string; desc: string };
  type WfSec    = { title: string; desc: string; items: WfItem[] };
  type SpecItem = { label: string; val: string };
  type FeatCard = { key: string; accent: string; title: string; items: string[] };

  const UI_STR: Record<GuideKey, Record<string, string>> = {
    zh: { arch: '系统架构', arch_hint: '点击各层查看详情', wf: '运行流程', wf_hint: '点击步骤查看详情', feat: '功能说明', feat_hint: '点击卡片查看技术规格', orch_inner: 'Orchestrator 内部', tech_specs: '技术规格' },
    en: { arch: 'System Architecture', arch_hint: 'Click a layer to explore', wf: 'Execution Flow', wf_hint: 'Click a step to learn more', feat: 'Features', feat_hint: 'Click a card for tech specs', orch_inner: 'Orchestrator internals', tech_specs: 'Tech Specs' },
  };

  const WF_STEPS: Record<GuideKey, { n: number; name: string; desc: string; accent?: boolean }[]> = {
    zh: [
      { n: 1, name: 'Input',        desc: 'Ticket JSON / 自然语言' },
      { n: 2, name: 'WebUI / API',  desc: 'SSE streaming' },
      { n: 3, name: 'Orchestrator', desc: 'ReAct · KB · MCP · LLM', accent: true },
      { n: 4, name: 'Session',      desc: 'trace · score · audit' },
      { n: 5, name: 'Output',       desc: 'JSON + Markdown' },
    ],
    en: [
      { n: 1, name: 'Input',        desc: 'Ticket JSON / Natural Language' },
      { n: 2, name: 'WebUI / API',  desc: 'SSE streaming' },
      { n: 3, name: 'Orchestrator', desc: 'ReAct · KB · MCP · LLM', accent: true },
      { n: 4, name: 'Session',      desc: 'trace · score · audit' },
      { n: 5, name: 'Output',       desc: 'JSON + Markdown' },
    ],
  };

  const FEAT_CARDS: Record<GuideKey, FeatCard[]> = {
    zh: [
      { key: 'ai',   accent: 'blue',  title: 'AI 能力',    items: ['支持 Anthropic Claude、Google Gemini、OpenRouter 多家 LLM', 'ReAct 推理循环，工具调用后自动继续生成', 'SSE 流式输出，Run / Chat 均支持实时响应', 'Session 级别记录 model 与 provider'] },
      { key: 'kb',   accent: 'green', title: '知识管理',   items: ['ChromaDB 向量知识库，支持 kb_search 工具调用', 'Wiki 页面管理，支持详情查看与 Markdown 下载', 'Vendor Docs 厂商文档库，SSE 流式解析', 'KB-augmented Chat，问答时自动检索知识'] },
      { key: 'mcp',  accent: 'teal',  title: 'MCP 集成',   items: ['JSON-RPC 2.0，支持 stdio 和 HTTP 两种传输', '工具前缀路由：mcp__fs__read_file', 'allowlist / denylist 工具过滤，全局审计开关', 'MCP tab 展示已注册服务器和工具列表'] },
      { key: 'eval', accent: 'amber', title: '评估与迭代', items: ['Golden Test Harness，多维度 evaluator 打分', 'Skill Lineage 版本树，支持 rollback 标记', 'OpenRouter / Gemini 两条 golden-test 管道', 'make golden-* 一键运行对比测试'] },
      { key: 'sec',  accent: 'red',   title: '安全与合规', items: ['PII 自动脱敏：邮箱、手机、IP、主机名等', '防二次脱敏：已有占位符不会被重复处理', 'MCP 配置禁止内联 secret，必须用环境变量', '全局 audit_every_call 审计开关'] },
      { key: 'ui',   accent: 'slate', title: '操作界面',   items: ['8 Tab WebUI：Run/Chat/KB/Wiki/VendorDoc/MCP/Iteration/Guide', 'REPL TUI，类 Claude Code 的终端交互体验', 'FastAPI REST + SSE，支持前后端分离部署', '暗色 / 亮色主题切换，响应式布局'] },
    ],
    en: [
      { key: 'ai',   accent: 'blue',  title: 'AI Capabilities',  items: ['Supports Anthropic Claude, Google Gemini, OpenRouter and more', 'ReAct reasoning loop, continues generation after tool calls', 'SSE streaming output, Run / Chat both support real-time responses', 'Session-level model and provider recording'] },
      { key: 'kb',   accent: 'green', title: 'Knowledge Mgmt',   items: ['ChromaDB vector knowledge base, supports kb_search tool calls', 'Wiki page management with detail view and Markdown download', 'Vendor Docs library with SSE streaming parsing', 'KB-augmented Chat, auto-retrieves knowledge during QA'] },
      { key: 'mcp',  accent: 'teal',  title: 'MCP Integration',  items: ['JSON-RPC 2.0, supports stdio and HTTP transports', 'Tool prefix routing: mcp__fs__read_file', 'allowlist / denylist filtering, global audit switch', 'MCP tab shows registered servers and tool lists'] },
      { key: 'eval', accent: 'amber', title: 'Eval & Iteration',  items: ['Golden Test Harness with multi-dimensional evaluator scoring', 'Skill Lineage version tree with rollback markers', 'OpenRouter / Gemini two golden-test pipelines', 'make golden-* for one-command comparison testing'] },
      { key: 'sec',  accent: 'red',   title: 'Security',         items: ['Auto PII masking: email, phone, IP, hostname rules', 'Double-redaction guard: existing placeholders are skipped', 'MCP config prohibits inline secrets, must use env vars', 'Global audit_every_call switch'] },
      { key: 'ui',   accent: 'slate', title: 'Interfaces',        items: ['8 Tab WebUI: Run/Chat/KB/Wiki/VendorDoc/MCP/Iteration/Guide', 'REPL TUI, Claude Code-style terminal interaction', 'FastAPI REST + SSE, supports separated deployment', 'Light / dark theme toggle, responsive layout'] },
    ],
  };

  const ARCH_DATA: Record<string, Record<GuideKey, Section>> = {
    interface: {
      zh: { title: 'Interface Layer — 用户入口', desc: '三种接口形式覆盖不同使用场景：浏览器交互、终端操作、CI/CD 脚本。', items: [
        { name: 'WebUI', tech: 'Svelte 5 + SvelteKit', desc: '8 个功能 Tab，SSE 实时流式渲染，支持亮色/暗色主题切换' },
        { name: 'TUI',   tech: 'Python Textual',       desc: 'REPL shell 交互，支持 /slash 命令，同进程调用 Python lib，零网络依赖' },
        { name: 'CLI',   tech: 'Python Typer',          desc: 'opspilot harness / golden-* 命令，适合 CI/CD 自动化场景' },
      ]},
      en: { title: 'Interface Layer — User Entrypoints', desc: 'Three interface types covering browser, terminal, and CI/CD scripting scenarios.', items: [
        { name: 'WebUI', tech: 'Svelte 5 + SvelteKit', desc: '8 functional tabs, real-time SSE streaming, light/dark theme support' },
        { name: 'TUI',   tech: 'Python Textual',       desc: 'REPL shell with /slash commands, in-process Python lib calls, zero network dependency' },
        { name: 'CLI',   tech: 'Python Typer',          desc: 'opspilot harness / golden-* commands, ideal for CI/CD automation' },
      ]},
    },
    api: {
      zh: { title: 'API Layer — 统一网关', desc: 'FastAPI 提供 REST + SSE 接口，所有 UI 层通过此层访问后端能力，支持前后端分离部署。', items: [
        { name: '/run · /run/stream',     desc: '提交工单；stream 变体以 SSE 逐步推送 orchestrator trace 事件' },
        { name: '/chat · /chat/stream',   desc: 'KB-augmented 对话，SSE 流式，自动检索相关知识片段' },
        { name: '/kb · /wiki · /vendordoc', desc: '知识库 CRUD：上传文档、查询、详情查看、JSON/Markdown 下载' },
        { name: '/mcp',                   desc: 'MCP 服务器注册状态与可用工具列表查询' },
        { name: '/iteration',             desc: 'Skill lineage 版本树查询，支持 rollback 标记历史' },
      ]},
      en: { title: 'API Layer — Unified Gateway', desc: 'FastAPI provides REST + SSE endpoints. All UI layers access backend capabilities through this layer, supporting separated deployment.', items: [
        { name: '/run · /run/stream',     desc: 'Submit tickets; stream variant pushes orchestrator trace events via SSE incrementally' },
        { name: '/chat · /chat/stream',   desc: 'KB-augmented chat, SSE streaming, auto-retrieves relevant knowledge chunks' },
        { name: '/kb · /wiki · /vendordoc', desc: 'Knowledge base CRUD: upload, query, detail view, JSON/Markdown download' },
        { name: '/mcp',                   desc: 'MCP server registration status and available tool list queries' },
        { name: '/iteration',             desc: 'Skill lineage version tree queries, with rollback history markers' },
      ]},
    },
    core: {
      zh: { title: 'Orchestrator Core — 推理引擎', desc: '系统核心，处理从 PII 脱敏到 LLM 推理再到评估的完整 ReAct 循环，每一步均写入不可变 trace。', items: [
        { name: 'Redactor',            desc: '正则规则引擎，识别并替换 PII（邮箱/手机/IP/主机名），防二次脱敏：已有 [REDACTED:...] 不再处理' },
        { name: 'Orchestrator (ReAct)', desc: 'Reasoning + Acting 交替：LLM 决策 → 工具调用（kb_search / mcp__*）→ 携带结果继续推理，直到完成或超 max_turns' },
        { name: 'Evaluators',          desc: '多维打分：字段完整性检查、关键词覆盖率、ev_must_not_contain（PII 泄露检测），输出 0–1 float' },
      ]},
      en: { title: 'Orchestrator Core — Reasoning Engine', desc: 'System core handling the complete ReAct loop from PII masking through LLM inference to evaluation. Every step written to an immutable trace.', items: [
        { name: 'Redactor',            desc: 'Regex rule engine identifying and replacing PII (email/phone/IP/hostname). Double-redaction guard: existing [REDACTED:...] markers are skipped' },
        { name: 'Orchestrator (ReAct)', desc: 'Reasoning + Acting alternates: LLM decides → tool call (kb_search / mcp__*) → result injected back → continue until done or max_turns reached' },
        { name: 'Evaluators',          desc: 'Multi-dimensional scoring: field completeness, keyword coverage, ev_must_not_contain (PII leak detection), outputs 0–1 float' },
      ]},
    },
    storage: {
      zh: { title: 'Storage — 本地嵌入式存储', desc: '全部使用嵌入式存储，零运维，数据文件对 git 友好，可离线运行。', items: [
        { name: 'ChromaDB',      tech: '向量数据库',      desc: '存储文档 embedding，支持语义相似度检索，通过 kb_search 工具暴露给 LLM' },
        { name: 'SQLite + FTS5', tech: '关系型 + 全文索引', desc: 'Session 存储与 append-only 审计日志，FTS5 支持中文 ngram(2,3) 全文搜索' },
        { name: 'Playbooks',     tech: 'YAML 配置',       desc: 'Skill 定义：prompt 模板、provider 配置、evaluator 规则，版本化管理' },
      ]},
      en: { title: 'Storage — Local Embedded', desc: 'All embedded storage, zero ops overhead, git-friendly data files, fully offline-capable.', items: [
        { name: 'ChromaDB',      tech: 'Vector DB',          desc: 'Stores document embeddings, semantic similarity retrieval, exposed to LLM via kb_search tool' },
        { name: 'SQLite + FTS5', tech: 'Relational + FTS',   desc: 'Session storage and append-only audit log, FTS5 supports Chinese ngram(2,3) full-text search' },
        { name: 'Playbooks',     tech: 'YAML config',        desc: 'Skill definitions: prompt templates, provider config, evaluator rules, version-controlled' },
      ]},
    },
    external: {
      zh: { title: 'External Services — 外部服务', desc: '通过统一 Provider 抽象接入多家 LLM，通过 MCP JSON-RPC 2.0 协议接入外部工具服务器。', items: [
        { name: 'LLM APIs',            desc: 'Anthropic Claude（默认）、Google Gemini、OpenRouter（含 GPT-4/Mixtral）、Grok（xAI）；Ollama 用于本地模型' },
        { name: 'MCP Servers (stdio)', desc: '以子进程启动，JSON-RPC 2.0 over stdin/stdout，支持 ${VAR:-default} 环境变量展开' },
        { name: 'MCP Servers (HTTP)',  desc: 'JSON-RPC 2.0 over HTTP POST，适合远程或已运行的 MCP 服务' },
      ]},
      en: { title: 'External Services', desc: 'Multiple LLMs via unified Provider abstraction; external tool servers via MCP JSON-RPC 2.0 protocol.', items: [
        { name: 'LLM APIs',            desc: 'Anthropic Claude (default), Google Gemini, OpenRouter (incl. GPT-4/Mixtral), Grok (xAI); Ollama for local models' },
        { name: 'MCP Servers (stdio)', desc: 'Launched as subprocess, JSON-RPC 2.0 over stdin/stdout, supports ${VAR:-default} env expansion' },
        { name: 'MCP Servers (HTTP)',  desc: 'JSON-RPC 2.0 over HTTP POST, suitable for remote or already-running MCP services' },
      ]},
    },
  };

  const WF_DATA: Record<number, Record<GuideKey, WfSec>> = {
    1: {
      zh: { title: 'Input — 工单输入', desc: '支持 JSON 直接提交或自然语言描述，统一进入 RunRequest schema 校验。', items: [
        { name: 'JSON 模式',   desc: '字段：title / description / severity(critical|high|medium|low) / tags[] / context{}' },
        { name: '自然语言模式', desc: 'WebUI NL tab 输入描述，系统自动映射到 RunRequest 字段结构' },
        { name: 'Schema 校验', desc: '输入先通过 Pydantic 校验，字段缺失或格式错误立即返回 400 而非进入 orchestrator' },
      ]},
      en: { title: 'Input — Ticket Submission', desc: 'Supports direct JSON or natural language input, unified through RunRequest schema validation.', items: [
        { name: 'JSON mode',              desc: 'Fields: title / description / severity(critical|high|medium|low) / tags[] / context{}' },
        { name: 'Natural language mode',  desc: 'Enter NL description in WebUI NL tab; system auto-maps to RunRequest fields' },
        { name: 'Schema validation',      desc: 'Pydantic validates first; missing fields or format errors return 400 immediately, never reaching orchestrator' },
      ]},
    },
    2: {
      zh: { title: 'WebUI / API — 请求层', desc: 'WebUI 通过 EventSource 建立 SSE 长连接，实时接收 orchestrator 推送的 trace 事件流。', items: [
        { name: 'SSE 连接',  desc: 'POST /api/run/stream 返回 text/event-stream，每个 trace 步骤独立推送，前端逐步渲染' },
        { name: '模型选择',  desc: '顶部 model selector 切换 provider 与模型，选择写入 RunRequest.model_ref（如 claude-sonnet-4-6）' },
        { name: '非流式模式', desc: 'POST /api/run 同步等待完整结果，适合 CLI / CI 自动化场景' },
      ]},
      en: { title: 'WebUI / API — Request Layer', desc: 'WebUI establishes an SSE long-polling connection via EventSource, receiving orchestrator trace events in real time.', items: [
        { name: 'SSE connection',  desc: 'POST /api/run/stream returns text/event-stream; each trace step pushed independently, frontend renders progressively' },
        { name: 'Model selection', desc: 'Top model selector switches provider and model; written to RunRequest.model_ref (e.g. claude-sonnet-4-6)' },
        { name: 'Non-streaming',   desc: 'POST /api/run synchronously waits for complete result, suitable for CLI / CI automation' },
      ]},
    },
    3: {
      zh: { title: 'Orchestrator — ReAct 推理循环', desc: 'Reasoning + Acting 交替，工具调用结果自动注入上下文，直到 LLM 输出最终 JSON 或超 max_turns 上限。', items: [
        { name: 'Redact',    desc: '对工单文本执行脱敏规则，PII 替换为 [REDACTED:type:hex]，原始值不进入 LLM 上下文' },
        { name: 'KB Search', desc: 'LLM 决定调用 kb_search 时，ChromaDB 语义检索最相关 top-k 文档片段注入 prompt' },
        { name: 'MCP Tools', desc: 'LLM 调用 mcp__<prefix>__<tool> 时，McpRegistry 路由到对应服务器执行并返回结果' },
        { name: 'LLM Call',  desc: '携带工具结果构建新 messages，发送给 Claude/Gemini/OpenRouter，获取下一步思考或最终输出' },
        { name: 'Evaluator', desc: '最终输出经多个 evaluator 打分，分数写入 session.score，高于阈值才视为成功' },
      ]},
      en: { title: 'Orchestrator — ReAct Loop', desc: 'Reasoning + Acting alternates; tool call results auto-injected into context until LLM outputs final JSON or max_turns is reached.', items: [
        { name: 'Redact',    desc: 'Apply redaction rules to ticket text; PII replaced with [REDACTED:type:hex], originals never enter LLM context' },
        { name: 'KB Search', desc: 'When LLM calls kb_search, ChromaDB semantically retrieves top-k most relevant document chunks for prompt injection' },
        { name: 'MCP Tools', desc: 'When LLM calls mcp__<prefix>__<tool>, McpRegistry routes to the corresponding server and returns result' },
        { name: 'LLM Call',  desc: 'Build new messages with tool results, send to Claude/Gemini/OpenRouter, receive next reasoning step or final output' },
        { name: 'Evaluator', desc: 'Final output scored by multiple evaluators; score written to session.score; above threshold = success' },
      ]},
    },
    4: {
      zh: { title: 'Session — 会话存储', desc: '每次 Run 生成一个不可变 session，包含完整执行轨迹、评分与审计信息。', items: [
        { name: 'trace[]', desc: '按步骤记录：actor（user/assistant/tool:kb/tool:mcp）、content、timestamp，append-only' },
        { name: 'score{}', desc: 'evaluator 输出 0–1 float，含各子项（field_completeness / keyword_coverage / pii_leak）' },
        { name: 'audit',   desc: '记录 model_ref、provider、工具调用次数、总 token 用量，满足合规审计要求' },
      ]},
      en: { title: 'Session — Session Storage', desc: 'Each Run generates an immutable session containing complete execution trace, scores, and audit information.', items: [
        { name: 'trace[]', desc: 'Step-by-step records: actor (user/assistant/tool:kb/tool:mcp), content, timestamp, append-only' },
        { name: 'score{}', desc: 'Evaluator outputs 0–1 float with sub-items (field_completeness / keyword_coverage / pii_leak)' },
        { name: 'audit',   desc: 'Records model_ref, provider, tool call count, total token usage, satisfying compliance audit requirements' },
      ]},
    },
    5: {
      zh: { title: 'Output — 结果交付', desc: '结果以 JSON 和 Markdown 两种格式导出，可直接归档到 Wiki 或下游系统消费。', items: [
        { name: 'RunResult JSON', desc: '字段：summary / tried_steps[] / root_cause / recommended_action / score / session_id' },
        { name: 'Markdown 导出',  desc: '人类可读报告，包含 trace 摘要与评分，适合写入 Wiki / Notion / Confluence' },
        { name: 'Skill Lineage', desc: '若执行 opspilot iteration promote，结果挂入版本树，可 rollback 到任意历史 skill 版本' },
      ]},
      en: { title: 'Output — Result Delivery', desc: 'Results exported as JSON and Markdown for direct archival to Wiki or downstream system consumption.', items: [
        { name: 'RunResult JSON', desc: 'Fields: summary / tried_steps[] / root_cause / recommended_action / score / session_id' },
        { name: 'Markdown export', desc: 'Human-readable report with trace summary and scores; suitable for Wiki / Notion / Confluence' },
        { name: 'Skill Lineage',  desc: 'If opspilot iteration promote is run, result is attached to version tree, enabling rollback to any historical skill version' },
      ]},
    },
  };

  const FEAT_EXTRA: Record<string, Record<GuideKey, { items: SpecItem[] }>> = {
    ai: {
      zh: { items: [{ label: '默认模型', val: 'claude-sonnet-4-6' }, { label: 'Provider 抽象', val: '自实现，不依赖 LiteLLM' }, { label: 'max_turns', val: '10（可在 playbook 配置）' }, { label: 'Token 计数', val: 'Ollama tokenizer / tiktoken' }] },
      en: { items: [{ label: 'Default model', val: 'claude-sonnet-4-6' }, { label: 'Provider abstraction', val: 'Custom, no LiteLLM dependency' }, { label: 'max_turns', val: '10 (configurable in playbook)' }, { label: 'Token counting', val: 'Ollama tokenizer / tiktoken' }] },
    },
    kb: {
      zh: { items: [{ label: '向量库', val: 'ChromaDB (embedded)' }, { label: 'Embedding 模型', val: 'nomic-embed-text via Ollama' }, { label: '检索 top-k', val: '5（可配置）' }, { label: '文档格式', val: 'PDF / DOCX / MD / TXT via markitdown' }] },
      en: { items: [{ label: 'Vector DB', val: 'ChromaDB (embedded)' }, { label: 'Embedding model', val: 'nomic-embed-text via Ollama' }, { label: 'Retrieval top-k', val: '5 (configurable)' }, { label: 'Document formats', val: 'PDF / DOCX / MD / TXT via markitdown' }] },
    },
    mcp: {
      zh: { items: [{ label: '协议版本', val: 'MCP 2024-11-05' }, { label: '传输方式', val: 'stdio（子进程）/ HTTP POST' }, { label: '工具路由', val: 'mcp__<server-id>__<tool-name>' }, { label: '安全', val: '禁止内联 secret，block_secrets_in_env_literals: true' }] },
      en: { items: [{ label: 'Protocol version', val: 'MCP 2024-11-05' }, { label: 'Transport', val: 'stdio (subprocess) / HTTP POST' }, { label: 'Tool routing', val: 'mcp__<server-id>__<tool-name>' }, { label: 'Security', val: 'No inline secrets, block_secrets_in_env_literals: true' }] },
    },
    eval: {
      zh: { items: [{ label: 'Evaluator 类型', val: 'field_check / keyword_coverage / must_not_contain' }, { label: '分数范围', val: '0.0 – 1.0 float' }, { label: 'Golden baseline', val: 'Anthropic 0.968 / Gemini 0.983 / OpenRouter 0.983' }, { label: '运行命令', val: 'make golden-* / opspilot harness golden-*' }] },
      en: { items: [{ label: 'Evaluator types', val: 'field_check / keyword_coverage / must_not_contain' }, { label: 'Score range', val: '0.0 – 1.0 float' }, { label: 'Golden baseline', val: 'Anthropic 0.968 / Gemini 0.983 / OpenRouter 0.983' }, { label: 'Run command', val: 'make golden-* / opspilot harness golden-*' }] },
    },
    sec: {
      zh: { items: [{ label: 'PII 规则', val: 'email / phone / ip / hostname / url' }, { label: '脱敏格式', val: '[REDACTED:type:hex8]' }, { label: '防二次脱敏', val: '已有占位符自动跳过' }, { label: 'MCP 审计', val: 'audit_every_call: true（全局）' }] },
      en: { items: [{ label: 'PII rules', val: 'email / phone / ip / hostname / url' }, { label: 'Redaction format', val: '[REDACTED:type:hex8]' }, { label: 'Double-redaction guard', val: 'Existing placeholders skipped automatically' }, { label: 'MCP audit', val: 'audit_every_call: true (global)' }] },
    },
    ui: {
      zh: { items: [{ label: 'WebUI 框架', val: 'Svelte 5 + SvelteKit + Vite' }, { label: 'TUI 框架', val: 'Python Textual' }, { label: 'API 框架', val: 'FastAPI + Uvicorn' }, { label: '主题', val: '亮色 / 暗色，CSS custom properties' }] },
      en: { items: [{ label: 'WebUI stack', val: 'Svelte 5 + SvelteKit + Vite' }, { label: 'TUI stack', val: 'Python Textual' }, { label: 'API stack', val: 'FastAPI + Uvicorn' }, { label: 'Theme', val: 'Light / dark, CSS custom properties' }] },
    },
  };

  // --- Core State ---
  let modelRef = $state<string | null>(null);
  let modules = $state<Record<string, boolean>>({ run: true, history: true });
  let availableModels = $state<ModelOption[]>([]);
  let selectedModelId = $state<string>('');
  let modelsLoaded = $state<boolean>(false);

  // --- Ticket Input ---
  let inputMode = $state<'nl' | 'json'>('nl');
  let nlInput = $state<string>('无法连接 VPN，从今早 09:00 起报错 Authentication failed，已重启客户端无效。');
  let ticketInput = $state<string>(JSON.stringify(
    {
      "ticket_id": "TKT-DEMO-001",
      "channel": "email",
      "submitted_at": "2026-05-01T09:00:00Z",
      "submitter_role": "end_user",
      "subject": "无法连接 VPN",
      "body": "从今早 09:00 起无法连接公司 VPN，错误信息：Authentication failed。已尝试重启客户端，问题依旧。"
    },
    null,
    2
  ));
  let loading = $state<boolean>(false);
  let statusLines = $state<string[]>([]);
  let result = $state<RunResponse | null>(null);
  let fetchError = $state<string | null>(null);

  // --- History ---
  let sessions = $state<SessionSummary[]>([]);
  let historyLoading = $state<boolean>(false);
  let expanded = $state<Record<string, boolean>>({});
  let sessionCache = $state<Record<string, RunResponse>>({});
  let sessionLoadingId = $state<string | null>(null);

  // --- Iteration ---
  let lineages = $state<SkillLineage[]>([]);
  let lineageLoading = $state<boolean>(false);
  let lineageError = $state<string | null>(null);
  let expandedSkill = $state<Record<string, boolean>>({});

  // --- KB ---
  let kbStats = $state<KBStats | null>(null);
  let kbDocs = $state<KBDoc[]>([]);
  let kbDocsLoading = $state<boolean>(false);
  let kbSearchQuery = $state<string>('');
  let kbSearchResults = $state<KBHit[]>([]);
  let kbSearchLoading = $state<boolean>(false);
  let kbSearchError = $state<string | null>(null);
  let kbSection = $state<'docs' | 'search' | 'conflicts' | 'corrections'>('docs');
  let kbCorrections = $state<KBCorrection[]>([]);
  let correctionsLoading = $state<boolean>(false);
  let correctionsError = $state<string | null>(null);
  let kbConflicts = $state<KBConflict[]>([]);
  let conflictsLoading = $state<boolean>(false);
  let conflictsError = $state<string | null>(null);
  let conflictStatusFilter = $state<'open' | 'all'>('open');
  let resolving = $state<Record<string, boolean>>({});
  let correctingChunkId = $state<string | null>(null);
  let correctReason = $state<string>('');
  let correctContent = $state<string>('');
  let correctLoading = $state<boolean>(false);
  let correctError = $state<string | null>(null);

  // --- Wiki ---
  let wikiDocId = $state<string>('');
  let wikiSessionId = $state<string>('');
  let wikiLoading = $state<boolean>(false);
  let wikiMsg = $state<string | null>(null);
  let wikiError = $state<string | null>(null);
  let wikiLintIssues = $state<WikiLintIssue[]>([]);
  let wikiLintLoading = $state<boolean>(false);
  let wikiPages = $state<WikiPageSummary[]>([]);
  let wikiPagesLoading = $state<boolean>(false);
  let wikiPageDetail = $state<WikiPageDetail | null>(null);
  let wikiPageDetailSlug = $state<string | null>(null);
  let wikiPageDetailLoading = $state<boolean>(false);

  // --- Vendor Doc ---
  let vendorDocList = $state<VendorDocSummary[]>([]);
  let vendorDocListLoading = $state<boolean>(false);
  let vendorDocDetail = $state<VendorDoc | null>(null);
  let vendorDocDetailFilename = $state<string | null>(null);
  let vendorDocDetailLoading = $state<boolean>(false);
  let vendorDocTopic = $state<string>('');
  let vendorDocTemplateId = $state<string>('sop_summary');
  let vendorDocVendorName = $state<string>('');
  let vendorDocLoading = $state<boolean>(false);
  let vendorDocStatusLines = $state<string[]>([]);
  let vendorDocResult = $state<VendorDoc | null>(null);
  let vendorDocError = $state<string | null>(null);
  let vendorDocUsage = $state<RunResponse['usage'] | null>(null);

  // --- MCP ---
  let mcpServers = $state<MCPServer[]>([]);
  let mcpLoading = $state<boolean>(false);
  let mcpError = $state<string | null>(null);

  // --- Chat ---
  let chatMessages = $state<ChatMessage[]>([]);
  let chatInput = $state<string>('');
  let chatLoading = $state<boolean>(false);
  let chatStatusLines = $state<string[]>([]);
  let chatError = $state<string | null>(null);
  let chatUsage = $state<{ input_tokens: number; output_tokens: number; cost_usd: number } | null>(null);

  // --- Derived ---
  let summary = $derived(result?.result ?? null);
  let runError = $derived(result?.error ?? null);

  // --- Init ---
  let _initialized = false;
  $effect(() => {
    if (_initialized) return;
    _initialized = true;
    (async () => {
      try {
        const cfg = await getConfig();
        modelRef = cfg.active_model_ref;
        modules = cfg.modules;
      } catch {
        modelRef = 'unknown';
      }
      try {
        const modelsRes = await getModels();
        availableModels = modelsRes.models;
        selectedModelId = modelsRes.default_id;
      } catch {
        // models unavailable
      } finally {
        modelsLoaded = true;
      }
      if (modules.history) await refreshHistory();
      if (modules.iteration !== false) await refreshLineage();
      await loadKBDocs();
    })();
  });

  // --- Run Handlers ---
  function buildTicketFromNL(): Record<string, unknown> {
    const lines = nlInput.split('\n');
    const subject = lines[0]?.trim() || 'Untitled issue';
    return {
      ticket_id: `TKT-WEB-${Date.now()}`,
      channel: 'web',
      submitted_at: new Date().toISOString(),
      submitter_role: 'end_user',
      subject,
      body: nlInput.trim(),
    };
  }

  let lastRunInput = $state<Record<string, unknown> | null>(null);

  const PLAYBOOK_BY_TYPE: Record<string, string> = {
    incident: 'pb_ticket_summary_zh',
    service_request: 'pb_request_fulfillment_zh',
  };

  // Run-tab work-item-type selector. 'auto' omits playbook_id so the backend
  // classifies (and may ask for confirmation); the others force a playbook.
  let selectedWorkItemType = $state<'auto' | 'incident' | 'service_request'>('auto');

  function selectedPlaybookId(): string | undefined {
    return selectedWorkItemType === 'auto' ? undefined : PLAYBOOK_BY_TYPE[selectedWorkItemType];
  }

  async function runWith(input: Record<string, unknown>, playbookId?: string) {
    fetchError = null;
    result = null;
    statusLines = [];
    lastRunInput = input;
    loading = true;
    try {
      for await (const event of runTicketStream(input, selectedModelId || undefined, playbookId)) {
        if (event.type === 'status') {
          statusLines = [...statusLines, event.message];
        } else if (event.type === 'result') {
          result = event.data;
          if (modules.history && !event.data.needs_confirmation) await refreshHistory();
        } else if (event.type === 'error') {
          fetchError = event.message;
        }
      }
    } catch (e) {
      fetchError = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function handleRun() {
    let input: Record<string, unknown>;
    if (inputMode === 'nl') {
      if (!nlInput.trim()) { fetchError = 'Please describe the issue.'; return; }
      input = buildTicketFromNL();
    } else {
      try {
        input = JSON.parse(ticketInput);
      } catch {
        fetchError = 'Invalid JSON in ticket input.';
        return;
      }
    }
    await runWith(input, selectedPlaybookId());
  }

  function confirmWorkItemType(workItemType: string) {
    if (!lastRunInput) return;
    runWith(lastRunInput, PLAYBOOK_BY_TYPE[workItemType] ?? PLAYBOOK_BY_TYPE.incident);
  }

  function copyText(text: string) {
    navigator.clipboard.writeText(text).catch(() => {});
  }

  function formatNextActions(actions: NextAction[]): string {
    return actions.map((a, i) => `${i + 1}. **${a.action}**\n   ${a.rationale}`).join('\n\n');
  }

  // incident_summary_v1 emits structured tasks[]; fall back to legacy
  // next_actions[] (no tier) for old session-history artifacts.
  function summaryTasks(s: TicketSummary): Task[] {
    if (s.tasks && s.tasks.length) return s.tasks;
    return (s.next_actions ?? []).map((a, i) => ({
      ref: `task-${i + 1}`,
      action: a.action,
      rationale: a.rationale,
      tier: undefined as unknown as Task['tier'],
      citations: a.citations,
    }));
  }

  function formatTasks(tasks: Task[]): string {
    return tasks
      .map((t, i) => `${i + 1}. ${t.tier ? `[${t.tier}] ` : ''}**${t.action}**\n   ${t.rationale}`)
      .join('\n\n');
  }

  // --- History Handlers ---
  async function refreshHistory() {
    historyLoading = true;
    try { sessions = await listSessions(); }
    catch { sessions = []; }
    finally { historyLoading = false; }
  }

  async function toggleSession(sessionId: string) {
    if (expanded[sessionId]) { expanded = { ...expanded, [sessionId]: false }; return; }
    if (!sessionCache[sessionId]) {
      sessionLoadingId = sessionId;
      try {
        const res = await getSession(sessionId);
        sessionCache = { ...sessionCache, [sessionId]: res };
      } catch { sessionLoadingId = null; return; }
      sessionLoadingId = null;
    }
    expanded = { ...expanded, [sessionId]: true };
  }

  // --- Iteration Handlers ---
  async function refreshLineage() {
    lineageLoading = true;
    lineageError = null;
    try { lineages = await getLineage(); }
    catch (e) { lineageError = e instanceof Error ? e.message : String(e); lineages = []; }
    finally { lineageLoading = false; }
  }

  function toggleSkill(name: string) {
    expandedSkill = { ...expandedSkill, [name]: !expandedSkill[name] };
  }

  // --- KB Handlers ---
  async function loadKBStats() {
    try { kbStats = await getKBStats(); } catch { /* non-critical */ }
  }

  async function loadKBDocs() {
    kbDocsLoading = true;
    try { [kbDocs] = await Promise.all([listKBDocs(), loadKBStats()]); }
    catch { kbDocs = []; }
    finally { kbDocsLoading = false; }
  }

  async function loadCorrections() {
    correctionsLoading = true;
    correctionsError = null;
    try { kbCorrections = await listCorrections(); await loadKBStats(); }
    catch (e) { correctionsError = e instanceof Error ? e.message : String(e); }
    finally { correctionsLoading = false; }
  }

  async function handleKBSearch() {
    if (!kbSearchQuery.trim()) return;
    kbSearchLoading = true;
    kbSearchError = null;
    kbSearchResults = [];
    try { kbSearchResults = await searchKB(kbSearchQuery.trim()); }
    catch (e) { kbSearchError = e instanceof Error ? e.message : String(e); }
    finally { kbSearchLoading = false; }
  }

  async function handleCorrect(chunkId: string) {
    if (!correctReason.trim() || !correctContent.trim()) return;
    correctLoading = true;
    correctError = null;
    try {
      await correctChunk(chunkId, correctContent.trim(), correctReason.trim());
      if (kbSearchQuery.trim()) kbSearchResults = await searchKB(kbSearchQuery.trim());
      await loadKBStats();
      correctingChunkId = null;
      correctReason = '';
      correctContent = '';
    } catch (e) { correctError = e instanceof Error ? e.message : String(e); }
    finally { correctLoading = false; }
  }

  // --- Wiki Handlers ---
  async function handleWikiIngest() {
    if (!wikiDocId.trim()) return;
    wikiLoading = true; wikiMsg = null; wikiError = null;
    try {
      const r = await wikiIngest(wikiDocId.trim());
      wikiMsg = `✓ Created wiki page: ${r.slug}`;
    } catch (e) { wikiError = e instanceof Error ? e.message : String(e); }
    finally { wikiLoading = false; }
  }

  async function handleWikiQueryToPage() {
    wikiLoading = true; wikiMsg = null; wikiError = null;
    try {
      const r = await wikiQueryToPage(wikiSessionId.trim() || undefined);
      wikiMsg = `✓ ${r.pages_created} page(s) created`;
    } catch (e) { wikiError = e instanceof Error ? e.message : String(e); }
    finally { wikiLoading = false; }
  }

  async function handleWikiLint() {
    wikiLintLoading = true;
    try { wikiLintIssues = await wikiLint(); }
    catch { wikiLintIssues = []; }
    finally { wikiLintLoading = false; }
  }

  async function handleWikiPromote(slug: string) {
    wikiLoading = true; wikiMsg = null; wikiError = null;
    try {
      const r = await wikiPromote(slug);
      wikiMsg = r.skipped ? `Skipped: ${r.skip_reason}` : `✓ ${slug}: ${r.old_state} → ${r.new_state}`;
    } catch (e) { wikiError = e instanceof Error ? e.message : String(e); }
    finally { wikiLoading = false; }
  }

  async function loadWikiPages() {
    wikiPagesLoading = true;
    try { wikiPages = await listWikiPages(); }
    catch { wikiPages = []; }
    finally { wikiPagesLoading = false; }
  }

  async function openWikiPage(slug: string) {
    if (wikiPageDetailSlug === slug) { wikiPageDetail = null; wikiPageDetailSlug = null; return; }
    wikiPageDetailLoading = true;
    wikiPageDetailSlug = slug;
    try { wikiPageDetail = await getWikiPage(slug); }
    catch { wikiPageDetail = null; }
    finally { wikiPageDetailLoading = false; }
  }

  // --- Vendor Doc Handlers ---
  async function loadVendorDocList() {
    vendorDocListLoading = true;
    try { vendorDocList = await listVendorDocs(); }
    catch { vendorDocList = []; }
    finally { vendorDocListLoading = false; }
  }

  async function openVendorDoc(filename: string) {
    if (vendorDocDetailFilename === filename) { vendorDocDetail = null; vendorDocDetailFilename = null; return; }
    vendorDocDetailLoading = true;
    vendorDocDetailFilename = filename;
    try { vendorDocDetail = await getVendorDoc(filename); }
    catch { vendorDocDetail = null; }
    finally { vendorDocDetailLoading = false; }
  }

  function downloadVendorDocJson() {
    if (!vendorDocDetail) return;
    const blob = new Blob([JSON.stringify(vendorDocDetail, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${vendorDocDetail.doc_ref}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function vendorDocToMarkdown(doc: VendorDoc): string {
    const lines: string[] = [`# ${doc.title}`, ''];
    if (doc.scope_note) lines.push(`> ${doc.scope_note}`, '');
    for (const s of doc.sections) lines.push(`## ${s.heading}`, '', s.content, '');
    if (doc.citations.length > 0) {
      lines.push('## Sources', '');
      for (const c of doc.citations)
        lines.push(`- **${c.id}** — ${c.source_path || c.document_id}${c.line_start ? ` L${c.line_start}–${c.line_end}` : ''}`);
    }
    return lines.join('\n');
  }

  function downloadVendorDocMarkdown() {
    if (!vendorDocDetail) return;
    const blob = new Blob([vendorDocToMarkdown(vendorDocDetail)], { type: 'text/markdown' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${vendorDocDetail.doc_ref}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function handleGenerateVendorDoc() {
    if (!vendorDocTopic.trim()) return;
    vendorDocLoading = true;
    vendorDocStatusLines = [];
    vendorDocError = null;
    vendorDocResult = null;
    vendorDocUsage = null;
    try {
      for await (const event of generateVendorDocStream({
        topic: vendorDocTopic.trim(),
        template_id: vendorDocTemplateId,
        vendor_name: vendorDocVendorName.trim(),
        language: 'en',
      })) {
        if (event.type === 'status') vendorDocStatusLines = [...vendorDocStatusLines, event.message];
        else if (event.type === 'result') {
          vendorDocResult = event.data.result as unknown as VendorDoc;
          vendorDocUsage = event.data.usage;
          if (event.data.error) vendorDocError = event.data.error;
        } else if (event.type === 'error') {
          vendorDocError = event.message;
        }
      }
    } catch (e) { vendorDocError = e instanceof Error ? e.message : String(e); }
    finally { vendorDocLoading = false; }
  }

  function copyVendorDoc() {
    if (!vendorDocResult) return;
    const text = [
      `# ${vendorDocResult.title}`,
      vendorDocResult.scope_note ? `\n_${vendorDocResult.scope_note}_` : '',
      '',
      ...vendorDocResult.sections.map(s => `## ${s.heading}\n\n${s.content}`),
    ].join('\n\n');
    navigator.clipboard.writeText(text).catch(() => {});
  }

  // --- Conflict Handlers ---
  async function loadConflicts() {
    conflictsLoading = true; conflictsError = null;
    try { kbConflicts = await listConflicts(conflictStatusFilter); }
    catch (e) { conflictsError = e instanceof Error ? e.message : String(e); kbConflicts = []; }
    finally { conflictsLoading = false; }
  }

  async function handleResolve(conflictId: string, resolution: string) {
    resolving = { ...resolving, [conflictId]: true };
    try { await resolveConflict(conflictId, resolution); await loadConflicts(); }
    catch (e) { conflictsError = e instanceof Error ? e.message : String(e); }
    finally { resolving = { ...resolving, [conflictId]: false }; }
  }

  // --- MCP Handlers ---
  async function loadMCPServers() {
    mcpLoading = true; mcpError = null;
    try { mcpServers = await listMCPServers(); }
    catch (e) { mcpError = e instanceof Error ? e.message : String(e); mcpServers = []; }
    finally { mcpLoading = false; }
  }

  // --- Chat Handlers ---
  async function handleChat() {
    if (!chatInput.trim() || chatLoading) return;
    const userMsg = chatInput.trim();
    chatInput = '';
    chatMessages = [...chatMessages, { role: 'user', content: userMsg }];
    chatLoading = true;
    chatStatusLines = [];
    chatError = null;
    try {
      for await (const event of chatStream([...chatMessages], selectedModelId || undefined)) {
        if (event.type === 'status') {
          chatStatusLines = [...chatStatusLines, event.message];
        } else if (event.type === 'result') {
          chatMessages = [...chatMessages, { role: 'assistant', content: event.data.content }];
          chatUsage = event.data.usage;
        } else if (event.type === 'error') {
          chatError = event.message;
        }
      }
    } catch (e) {
      chatError = e instanceof Error ? e.message : String(e);
    } finally {
      chatLoading = false;
      chatStatusLines = [];
    }
  }

  function handleChatKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleChat();
    }
  }
</script>

<div class="app">
  <!-- Header -->
  <header>
    <h1>OpsPilot</h1>
    {#if !modelsLoaded}
      <span class="model-ref">Loading...</span>
    {:else if availableModels.length > 1}
      <select class="model-select" bind:value={selectedModelId} disabled={loading}>
        {#each availableModels as m}
          <option value={m.id}>{m.label}</option>
        {/each}
      </select>
    {:else}
      <span class="model-ref" title="Active model">{selectedModelId || modelRef || '—'}</span>
    {/if}
    <button class="theme-toggle" onclick={toggleTheme} title="Toggle dark mode" aria-label="Toggle dark mode">
      {theme === 'dark' ? '☀' : '☾'}
    </button>
  </header>

  <!-- Tab Navigation -->
  <nav class="tab-nav">
    {#each ([
      { id: 'run', label: 'Run' },
      { id: 'chat', label: 'Chat' },
      { id: 'kb', label: 'Knowledge Base' },
      { id: 'wiki', label: 'Wiki' },
      { id: 'vendordoc', label: 'Vendor Docs' },
      { id: 'mcp', label: 'MCP' },
      { id: 'iteration', label: 'Iteration' },
      { id: 'guide', label: 'Guide' },
    ] as const) as tab}
      <button
        class="nav-tab {activeTab === tab.id ? 'active' : ''}"
        onclick={() => activeTab = tab.id}
      >{tab.label}</button>
    {/each}
  </nav>

  <main>

    <!-- ══════════════════════════════ RUN TAB ══════════════════════════════ -->
    {#if activeTab === 'run'}
      <section class="input-section">
        <div class="input-section-header">
          <h2>Ticket Input</h2>
          <div class="mode-toggle">
            <button
              class="mode-btn {inputMode === 'nl' ? 'active' : ''}"
              onclick={() => inputMode = 'nl'}
            >Natural Language</button>
            <button
              class="mode-btn {inputMode === 'json' ? 'active' : ''}"
              onclick={() => inputMode = 'json'}
            >JSON</button>
          </div>
        </div>

        {#if inputMode === 'nl'}
          <textarea
            rows={5}
            bind:value={nlInput}
            placeholder="Describe the issue in plain text, e.g.: Cannot connect to VPN since 09:00, error: Authentication failed. Already restarted the client."
            disabled={loading}
            class="nl-textarea"
          ></textarea>
        {:else}
          <textarea
            rows={12}
            bind:value={ticketInput}
            placeholder="Paste ticket JSON here..."
            disabled={loading}
          ></textarea>
        {/if}

        <div class="run-row">
          <label class="wi-type-label">
            Type
            <select class="wi-type-select" bind:value={selectedWorkItemType} disabled={loading}>
              <option value="auto">Auto-detect</option>
              <option value="incident">Incident</option>
              <option value="service_request">Service Request</option>
            </select>
          </label>
          <button class="btn-run" onclick={() => handleRun()} disabled={loading}>
            {#if loading}
              <span class="spinner"></span> Running...
            {:else}
              Run
            {/if}
          </button>
          {#if result?.usage}
            <span class="usage-badge">
              ↑ {result.usage.input_tokens.toLocaleString()} / ↓ {result.usage.output_tokens.toLocaleString()} tokens
              {#if result.usage.cost_usd > 0}· ${result.usage.cost_usd.toFixed(4)}{/if}
            </span>
          {/if}
        </div>
      </section>

      {#if statusLines.length > 0}
        <div class="status-log">
          {#each statusLines as line}
            <div class="status-line">› {line}</div>
          {/each}
          {#if loading}<div class="status-line status-line--active">…</div>{/if}
        </div>
      {/if}

      {#if fetchError}
        <div class="error-banner"><strong>Error:</strong> {fetchError}</div>
      {/if}
      {#if runError}
        <div class="error-banner"><strong>Run error:</strong> {runError}</div>
      {/if}

      {#snippet outputCards(s: TicketSummary)}
        <section class="cards">
          <div class="card">
            <div class="card-header">
              <h3>Summary</h3>
              <button class="btn-copy" onclick={() => copyText(s.summary ?? '')}>Copy</button>
            </div>
            <p>{s.summary}</p>
          </div>
          {#if s.requested_item}
          <div class="card">
            <div class="card-header">
              <h3>Requested Item</h3>
              <button class="btn-copy" onclick={() => copyText(s.requested_item ?? '')}>Copy</button>
            </div>
            <p>{s.requested_item}</p>
          </div>
          {/if}
          {#if s.symptoms?.length}
          <div class="card">
            <div class="card-header">
              <h3>Symptoms</h3>
              <button class="btn-copy" onclick={() => copyText((s.symptoms ?? []).join('\n'))}>Copy</button>
            </div>
            <ul>
              {#each s.symptoms as symptom}<li>{symptom}</li>{/each}
            </ul>
          </div>
          {/if}
          <div class="card">
            <div class="card-header">
              <h3>Tasks</h3>
              <button class="btn-copy" onclick={() => copyText(formatTasks(summaryTasks(s)))}>Copy</button>
            </div>
            <ol>
              {#each summaryTasks(s) as task}
                <li>
                  {#if task.tier}<span class="tier-badge tier-{task.tier}">{task.tier}</span>{/if}
                  <strong>{task.action}</strong>
                  <p class="rationale">{task.rationale}</p>
                </li>
              {/each}
            </ol>
          </div>
          {#if s.severity_suggested}
          <div class="card">
            <div class="card-header">
              <h3>Severity</h3>
              <button class="btn-copy" onclick={() => copyText((s.severity_suggested ?? '') + (s.escalation_hint ? '\n' + s.escalation_hint : ''))}>Copy</button>
            </div>
            <span class="severity-badge">{s.severity_suggested}</span>
            {#if s.escalation_hint}<p class="escalation">{s.escalation_hint}</p>{/if}
          </div>
          {/if}
          {#if s.approval_needed !== undefined}
          <div class="card">
            <div class="card-header">
              <h3>Approval</h3>
              <button class="btn-copy" onclick={() => copyText(s.approval_needed ? 'Approval needed' : 'Auto-fulfill')}>Copy</button>
            </div>
            <span class="severity-badge">{s.approval_needed ? 'Approval needed' : 'Auto-fulfill'}</span>
          </div>
          {/if}
        </section>
      {/snippet}

      {#if result?.needs_confirmation && result.classification}
        <div class="confirm-banner">
          <p>
            <strong>Low confidence — please confirm the work item type.</strong>
            Best guess: <span class="wi-badge">{result.classification.work_item_type}</span>
            ({(result.classification.confidence * 100).toFixed(0)}%) —
            {result.classification.rationale}
          </p>
          <div class="confirm-actions">
            <button class="btn-confirm" onclick={() => confirmWorkItemType('incident')}>Run as Incident</button>
            <button class="btn-confirm" onclick={() => confirmWorkItemType('service_request')}>Run as Service Request</button>
          </div>
        </div>
      {:else if result?.classification}
        <p class="classified-note">
          Classified as <span class="wi-badge">{result.classification.work_item_type}</span>
          ({(result.classification.confidence * 100).toFixed(0)}% confidence)
        </p>
      {/if}

      {#if summary}
        {@render outputCards(summary as TicketSummary)}
      {/if}

      <!-- History -->
      {#if modules.history}
        <section class="history-section">
          <div class="history-header">
            <h2>History</h2>
            <button class="btn-refresh" onclick={refreshHistory} disabled={historyLoading}>
              {historyLoading ? '...' : '↻'}
            </button>
          </div>
          {#if sessions.length === 0}
            <p class="history-empty">No sessions yet.</p>
          {:else}
            <table class="history-table">
              <thead>
                <tr><th>Time</th><th>Session ID</th><th>Status</th><th></th></tr>
              </thead>
              <tbody>
                {#each sessions as s}
                  <tr>
                    <td class="col-time">{new Date(s.created_at).toLocaleString()}</td>
                    <td class="col-sid mono">{s.session_id.slice(0, 26)}…</td>
                    <td><span class="status-badge status-{s.status}">{s.status}</span></td>
                    <td>
                      <button class="btn-view" onclick={() => toggleSession(s.session_id)}
                        disabled={sessionLoadingId === s.session_id}>
                        {#if sessionLoadingId === s.session_id}…
                        {:else if expanded[s.session_id]}▲ Hide
                        {:else}▼ View{/if}
                      </button>
                    </td>
                  </tr>
                  {#if expanded[s.session_id] && sessionCache[s.session_id]}
                    {@const sd = sessionCache[s.session_id]}
                    <tr class="expanded-row">
                      <td colspan="4">
                        <div class="session-detail">
                          <div class="session-detail-meta">
                            <span class="mono dim">{sd.session_id}</span>
                            {#if sd.artifact_id}<span class="dim">· artifact <span class="mono">{sd.artifact_id}</span></span>{/if}
                            {#if sd.usage}
                              <span class="usage-badge">
                                ↑ {sd.usage.input_tokens.toLocaleString()} / ↓ {sd.usage.output_tokens.toLocaleString()} tokens
                                {#if sd.usage.cost_usd > 0}· ${sd.usage.cost_usd.toFixed(4)}{/if}
                              </span>
                            {/if}
                          </div>
                          {#if sd.error}
                            <div class="error-banner" style="margin:0.5rem 0"><strong>Error:</strong> {sd.error}</div>
                          {:else if sd.result}
                            {@render outputCards(sd.result as TicketSummary)}
                          {/if}
                        </div>
                      </td>
                    </tr>
                  {/if}
                {/each}
              </tbody>
            </table>
          {/if}
        </section>
      {/if}
    {/if}

    <!-- ══════════════════════════════ CHAT TAB ══════════════════════════════ -->
    {#if activeTab === 'chat'}
      <section class="chat-section">
        <div class="chat-messages" id="chat-messages">
          {#if chatMessages.length === 0}
            <div class="chat-empty">
              <p>Ask anything about your IT operations. OpsPilot will search the knowledge base and answer.</p>
              <div class="chat-suggestions">
                <button class="suggestion-btn" onclick={() => { chatInput = 'How do I troubleshoot VPN authentication failures?'; handleChat(); }}>
                  VPN authentication failures
                </button>
                <button class="suggestion-btn" onclick={() => { chatInput = 'What are common causes of network connectivity issues?'; handleChat(); }}>
                  Network connectivity issues
                </button>
                <button class="suggestion-btn" onclick={() => { chatInput = 'How do I reset a user password?'; handleChat(); }}>
                  Reset user password
                </button>
              </div>
            </div>
          {:else}
            {#each chatMessages as msg}
              <div class="chat-bubble {msg.role}">
                <div class="bubble-content">{msg.content}</div>
              </div>
            {/each}
            {#if chatLoading && chatStatusLines.length > 0}
              <div class="chat-bubble assistant">
                <div class="bubble-content chat-thinking">
                  {chatStatusLines[chatStatusLines.length - 1]}…
                </div>
              </div>
            {/if}
          {/if}
        </div>

        {#if chatError}
          <div class="error-banner" style="margin: 0.5rem 0"><strong>Error:</strong> {chatError}</div>
        {/if}

        <div class="chat-input-row">
          <textarea
            class="chat-input"
            rows={2}
            bind:value={chatInput}
            placeholder="Ask a question… (Enter to send, Shift+Enter for newline)"
            disabled={chatLoading}
            onkeydown={handleChatKeydown}
          ></textarea>
          <button class="btn-chat-send" onclick={handleChat} disabled={chatLoading || !chatInput.trim()}>
            {#if chatLoading}
              <span class="spinner"></span>
            {:else}
              ↑
            {/if}
          </button>
        </div>

        <div class="chat-footer">
          {#if chatUsage}
            <span class="usage-badge">
              ↑ {chatUsage.input_tokens.toLocaleString()} / ↓ {chatUsage.output_tokens.toLocaleString()} tokens
              {#if chatUsage.cost_usd > 0}· ${chatUsage.cost_usd.toFixed(4)}{/if}
            </span>
          {/if}
          {#if chatMessages.length > 0}
            <button class="btn-sm" onclick={() => { chatMessages = []; chatUsage = null; chatError = null; }}>
              Clear chat
            </button>
          {/if}
        </div>
      </section>
    {/if}

    <!-- ══════════════════════════════ KB TAB ══════════════════════════════ -->
    {#if activeTab === 'kb'}
      <section class="kb-section">
        <div class="section-header">
          <h2>Knowledge Base</h2>
          <div class="section-tabs">
            <button class="tab-btn {kbSection === 'docs' ? 'active' : ''}" onclick={() => kbSection = 'docs'}>Docs</button>
            <button class="tab-btn {kbSection === 'search' ? 'active' : ''}" onclick={() => kbSection = 'search'}>Search</button>
            <button class="tab-btn {kbSection === 'conflicts' ? 'active' : ''}" onclick={() => { kbSection = 'conflicts'; loadConflicts(); }}>
              Conflicts {#if kbStats && kbStats.open_conflicts > 0}<span class="conflict-badge">{kbStats.open_conflicts}</span>{/if}
            </button>
            <button class="tab-btn {kbSection === 'corrections' ? 'active' : ''}" onclick={() => { kbSection = 'corrections'; loadCorrections(); }}>
              Corrections {#if kbStats && kbStats.corrections_total > 0}<span class="corr-badge">{kbStats.corrections_total}</span>{/if}
            </button>
          </div>
          <button class="btn-refresh" onclick={loadKBDocs} disabled={kbDocsLoading}>↻</button>
        </div>

        {#if kbStats}
          <div class="kb-stats-bar">
            <span class="stat-item"><strong>{kbStats.docs_total}</strong> docs</span>
            <span class="stat-sep">·</span>
            <span class="stat-item"><strong>{kbStats.chunks_total}</strong> chunks</span>
            <span class="stat-sep">·</span>
            <span class="stat-item {kbStats.open_conflicts > 0 ? 'stat-warn' : ''}">
              <strong>{kbStats.open_conflicts}</strong> open conflicts
            </span>
            <span class="stat-sep">·</span>
            <span class="stat-item"><strong>{kbStats.corrections_total}</strong> corrections</span>
          </div>
        {/if}

        {#if kbSection === 'docs'}
          {#if kbDocsLoading}
            <p class="section-empty">Loading…</p>
          {:else if kbDocs.length === 0}
            <p class="section-empty">No documents ingested yet. Use <code>opspilot ingest &lt;file&gt;</code> or the TUI.</p>
          {:else}
            <table class="data-table">
              <thead><tr><th>Doc ID</th><th>Title</th><th>Lang</th><th>Chunks</th><th>Ingested</th></tr></thead>
              <tbody>
                {#each kbDocs as doc}
                  <tr>
                    <td class="mono">{doc.doc_id}</td>
                    <td>{doc.title || '—'}</td>
                    <td>{doc.language || '—'}</td>
                    <td class="num">{doc.chunk_count}</td>
                    <td class="dim">{doc.ingested_at.slice(0, 10)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}
        {:else if kbSection === 'search'}
          <div class="search-row">
            <input class="search-input" bind:value={kbSearchQuery} placeholder="Search KB…"
              onkeydown={(e) => e.key === 'Enter' && handleKBSearch()} />
            <button class="btn-action" onclick={handleKBSearch} disabled={kbSearchLoading || !kbSearchQuery.trim()}>
              {kbSearchLoading ? '…' : 'Search'}
            </button>
          </div>
          {#if kbSearchError}
            <p class="section-error">{kbSearchError}</p>
          {:else if kbSearchResults.length > 0}
            <table class="data-table">
              <thead><tr><th>Chunk</th><th>Doc</th><th>Score</th><th>Valid From</th><th>Snippet</th><th></th></tr></thead>
              <tbody>
                {#each kbSearchResults as h}
                  <tr class="{h.has_open_conflicts ? 'row-conflict' : ''}">
                    <td class="mono">{h.chunk_id.slice(0, 20)}</td>
                    <td class="mono">
                      {h.document_id.slice(0, 20)}
                      {#if h.has_open_conflicts}<span class="warn-badge" title="Source document has open conflicts">⚠</span>{/if}
                    </td>
                    <td class="num">{h.score.toFixed(4)}</td>
                    <td class="dim">{h.valid_from ? h.valid_from.slice(0, 10) : '—'}</td>
                    <td class="snippet">{h.content.slice(0, 100)}</td>
                    <td>
                      <button class="btn-correct-toggle" title="Correct this chunk"
                        onclick={() => {
                          correctingChunkId = correctingChunkId === h.chunk_id ? null : h.chunk_id;
                          correctReason = '';
                          correctContent = h.content;
                          correctError = null;
                        }}>
                        {correctingChunkId === h.chunk_id ? '✕' : '✎'}
                      </button>
                    </td>
                  </tr>
                  {#if correctingChunkId === h.chunk_id}
                    <tr class="correct-row">
                      <td colspan="6">
                        <div class="correct-form">
                          <label class="correct-label">Reason
                            <input class="correct-input" bind:value={correctReason} placeholder="Why is this content incorrect?" />
                          </label>
                          <label class="correct-label">Corrected content
                            <textarea class="correct-textarea" bind:value={correctContent} rows="4"></textarea>
                          </label>
                          {#if correctError}<p class="section-error">{correctError}</p>{/if}
                          <div class="correct-actions">
                            <button class="btn-action" onclick={() => handleCorrect(h.chunk_id)}
                              disabled={correctLoading || !correctReason.trim() || !correctContent.trim()}>
                              {correctLoading ? '…' : 'Apply correction'}
                            </button>
                            <button class="btn-secondary" onclick={() => correctingChunkId = null}>Cancel</button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  {/if}
                {/each}
              </tbody>
            </table>
          {:else if !kbSearchLoading && kbSearchQuery}
            <p class="section-empty">No results.</p>
          {/if}
        {:else if kbSection === 'conflicts'}
          <div class="conflict-toolbar">
            <label class="filter-label">
              Show:
              <select bind:value={conflictStatusFilter} onchange={loadConflicts}>
                <option value="open">Open only</option>
                <option value="all">All</option>
              </select>
            </label>
            <button class="btn-refresh" onclick={loadConflicts} disabled={conflictsLoading}>↻</button>
          </div>
          {#if conflictsError}
            <p class="section-error">{conflictsError}</p>
          {:else if conflictsLoading}
            <p class="section-empty">Loading…</p>
          {:else if kbConflicts.length === 0}
            <p class="section-empty">No {conflictStatusFilter === 'open' ? 'open ' : ''}conflicts found.</p>
          {:else}
            <table class="data-table conflict-table">
              <thead>
                <tr><th>Type</th><th>Sim</th><th>Doc A</th><th>Doc B</th><th>Status</th><th>Actions</th></tr>
              </thead>
              <tbody>
                {#each kbConflicts as c}
                  <tr>
                    <td><span class="conflict-type-badge ctype-{c.conflict_type}">{c.conflict_type.replace('_', ' ')}</span></td>
                    <td class="num">{c.similarity.toFixed(3)}</td>
                    <td>
                      <div class="conflict-doc">{c.doc_a_title || c.doc_a_id}</div>
                      {#if c.doc_a_valid_from}<div class="dim" style="font-size:0.75rem">{c.doc_a_valid_from.slice(0,10)}</div>{/if}
                      {#if c.chunk_a_content}<div class="chunk-preview">{c.chunk_a_content.slice(0, 80)}…</div>{/if}
                    </td>
                    <td>
                      <div class="conflict-doc">{c.doc_b_title || c.doc_b_id}</div>
                      {#if c.doc_b_valid_from}<div class="dim" style="font-size:0.75rem">{c.doc_b_valid_from.slice(0,10)}</div>{/if}
                      {#if c.chunk_b_content}<div class="chunk-preview">{c.chunk_b_content.slice(0, 80)}…</div>{/if}
                    </td>
                    <td><span class="status-badge status-{c.status}">{c.status}</span></td>
                    <td>
                      {#if c.status === 'open'}
                        <div class="resolve-btns">
                          <button class="btn-sm btn-a-wins" onclick={() => handleResolve(c.id, 'a_wins')} disabled={resolving[c.id]}>A wins</button>
                          <button class="btn-sm btn-b-wins" onclick={() => handleResolve(c.id, 'b_wins')} disabled={resolving[c.id]}>B wins</button>
                          <button class="btn-sm" onclick={() => handleResolve(c.id, 'dismissed')} disabled={resolving[c.id]}>Dismiss</button>
                        </div>
                      {:else}
                        <span class="dim" style="font-size:0.8rem">{c.resolved_by || '—'}</span>
                      {/if}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}
        {:else}
          <div class="conflict-toolbar">
            <button class="btn-refresh" onclick={loadCorrections} disabled={correctionsLoading}>↻ Refresh</button>
          </div>
          {#if correctionsError}
            <p class="section-error">{correctionsError}</p>
          {:else if correctionsLoading}
            <p class="section-empty">Loading…</p>
          {:else if kbCorrections.length === 0}
            <p class="section-empty">No corrections recorded.</p>
          {:else}
            <table class="data-table">
              <thead>
                <tr><th>ID</th><th>Chunk</th><th>By</th><th>Reason</th><th>Old content</th><th>New content</th><th>Created</th></tr>
              </thead>
              <tbody>
                {#each kbCorrections as corr}
                  <tr>
                    <td class="mono dim">{corr.id}</td>
                    <td class="mono">{corr.chunk_id}</td>
                    <td class="dim">{corr.corrected_by}</td>
                    <td>{corr.reason}</td>
                    <td class="chunk-preview dim">{corr.old_content.slice(0, 80)}</td>
                    <td class="chunk-preview">{corr.new_content.slice(0, 80)}</td>
                    <td class="dim">{corr.created_at.slice(0, 19)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}
        {/if}
      </section>
    {/if}

    <!-- ══════════════════════════════ WIKI TAB ══════════════════════════════ -->
    {#if activeTab === 'wiki'}
      <section class="wiki-section">
        <div class="section-header"><h2>Wiki</h2></div>
        <div class="action-row">
          <input class="short-input" bind:value={wikiDocId} placeholder="KB doc_id for ingest…" />
          <button class="btn-action" onclick={handleWikiIngest} disabled={wikiLoading || !wikiDocId.trim()}>Ingest KB Doc</button>
          <input class="short-input" bind:value={wikiSessionId} placeholder="Session ID (blank=scan all)" />
          <button class="btn-action" onclick={handleWikiQueryToPage} disabled={wikiLoading}>Query→Page</button>
          <button class="btn-action btn-secondary" onclick={handleWikiLint} disabled={wikiLintLoading}>
            {wikiLintLoading ? '…' : 'Lint'}
          </button>
        </div>
        {#if wikiMsg}<p class="section-ok">{wikiMsg}</p>{/if}
        {#if wikiError}<p class="section-error">{wikiError}</p>{/if}
        {#if wikiLintIssues.length > 0}
          <table class="data-table">
            <thead><tr><th>Severity</th><th>Type</th><th>Page</th><th>Summary</th><th></th></tr></thead>
            <tbody>
              {#each wikiLintIssues as issue}
                <tr>
                  <td><span class="sev-badge sev-{issue.severity}">{issue.severity}</span></td>
                  <td class="mono">{issue.issue_type}</td>
                  <td class="mono">{issue.page_slug}</td>
                  <td>{issue.summary.slice(0, 60)}</td>
                  <td>
                    {#if issue.page_slug}
                      <button class="btn-sm" onclick={() => handleWikiPromote(issue.page_slug)}>Promote</button>
                    {/if}
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {:else if !wikiLintLoading}
          <p class="section-empty">Run lint to check wiki pages.</p>
        {/if}
        <div class="action-row" style="margin-top:1rem">
          <button class="btn-action btn-secondary" onclick={loadWikiPages} disabled={wikiPagesLoading}>
            {wikiPagesLoading ? '…' : 'List Pages'}
          </button>
        </div>
        {#if wikiPages.length > 0}
          <table class="data-table" style="margin-top:0.5rem">
            <thead><tr><th>Slug</th><th>Kind</th><th>Title</th><th>State</th><th>Lang</th></tr></thead>
            <tbody>
              {#each wikiPages as p}
                <tr class="clickable-row" onclick={() => openWikiPage(p.slug)}
                    class:expanded-row={wikiPageDetailSlug === p.slug}>
                  <td class="mono">{p.slug}</td>
                  <td><span class="sev-badge sev-info">{p.kind}</span></td>
                  <td>{p.title}</td>
                  <td><span class="sev-badge sev-{p.lifecycle_state === 'live' ? 'ok' : 'warn'}">{p.lifecycle_state}</span></td>
                  <td class="mono dim">{p.language}</td>
                </tr>
                {#if wikiPageDetailSlug === p.slug}
                  <tr class="detail-row">
                    <td colspan="5">
                      {#if wikiPageDetailLoading}
                        <p class="dim" style="padding:0.5rem">Loading…</p>
                      {:else if wikiPageDetail}
                        <div class="wiki-detail">
                          <p class="wiki-detail-summary dim">{wikiPageDetail.summary}</p>
                          {#if wikiPageDetail.tags.length > 0}
                            <div class="wiki-detail-tags">
                              {#each wikiPageDetail.tags as tag}<span class="sev-badge sev-info">{tag}</span>{/each}
                            </div>
                          {/if}
                          <pre class="wiki-detail-body">{wikiPageDetail.body}</pre>
                        </div>
                      {/if}
                    </td>
                  </tr>
                {/if}
              {/each}
            </tbody>
          </table>
        {:else if !wikiPagesLoading}
          <p class="section-empty" style="margin-top:0.5rem">No pages yet — click List Pages.</p>
        {/if}
      </section>
    {/if}

    <!-- ══════════════════════════ VENDOR DOCS TAB ══════════════════════════ -->
    {#if activeTab === 'vendordoc'}
      <section class="vendordoc-section">
        <div class="section-header">
          <h2>Vendor Document</h2>
          {#if vendorDocResult}
            <button class="btn-action btn-secondary" onclick={copyVendorDoc}>Copy as Markdown</button>
          {/if}
        </div>
        <div class="vd-form">
          <div class="vd-row">
            <label class="vd-label">Topic
              <input class="vd-input" bind:value={vendorDocTopic}
                placeholder="e.g. VPN authentication failure troubleshooting"
                disabled={vendorDocLoading} />
            </label>
            <label class="vd-label">Template
              <select class="vd-select" bind:value={vendorDocTemplateId} disabled={vendorDocLoading}>
                <option value="sop_summary">SOP Summary</option>
                <option value="maintenance_window">Maintenance Window</option>
                <option value="incident_report">Incident Report</option>
                <option value="handover">Handover Checklist</option>
              </select>
            </label>
            <label class="vd-label">Vendor (optional)
              <input class="vd-input vd-input-sm" bind:value={vendorDocVendorName}
                placeholder="e.g. SecureNet Ltd" disabled={vendorDocLoading} />
            </label>
          </div>
          <div class="vd-actions">
            <button class="btn-run" onclick={handleGenerateVendorDoc}
              disabled={vendorDocLoading || !vendorDocTopic.trim()}>
              {#if vendorDocLoading}<span class="spinner"></span> Generating…{:else}Generate{/if}
            </button>
            {#if vendorDocUsage}
              <span class="usage-badge">
                ↑ {vendorDocUsage.input_tokens.toLocaleString()} / ↓ {vendorDocUsage.output_tokens.toLocaleString()} tokens
                {#if vendorDocUsage.cost_usd > 0}· ${vendorDocUsage.cost_usd.toFixed(4)}{/if}
              </span>
            {/if}
          </div>
        </div>
        {#if vendorDocStatusLines.length > 0}
          <div class="status-log" style="margin-top:0.75rem">
            {#each vendorDocStatusLines as line}<div class="status-line">› {line}</div>{/each}
            {#if vendorDocLoading}<div class="status-line status-line--active">…</div>{/if}
          </div>
        {/if}
        {#if vendorDocError}<p class="section-error" style="margin-top:0.5rem">{vendorDocError}</p>{/if}
        {#if vendorDocResult}
          <div class="vd-output">
            <div class="vd-doc-header">
              <div>
                <div class="vd-title">{vendorDocResult.title}</div>
                <div class="vd-meta">
                  <span class="vd-ref mono dim">{vendorDocResult.doc_ref}</span>
                  <span class="vd-template-badge">{vendorDocResult.template_id.replace('_', ' ')}</span>
                </div>
              </div>
            </div>
            {#if vendorDocResult.scope_note}<p class="vd-scope-note">{vendorDocResult.scope_note}</p>{/if}
            {#each vendorDocResult.sections as section}
              <div class="vd-section">
                <h4 class="vd-section-heading">{section.heading}</h4>
                <p class="vd-section-content">{section.content}</p>
                {#if section.citations.length > 0}
                  <div class="vd-section-cits">
                    {#each section.citations as cit}<span class="vd-cit-tag">{cit}</span>{/each}
                  </div>
                {/if}
              </div>
            {/each}
            {#if vendorDocResult.citations.length > 0}
              <details class="vd-citations">
                <summary class="vd-cit-summary">Sources ({vendorDocResult.citations.length})</summary>
                <ul class="vd-cit-list">
                  {#each vendorDocResult.citations as c}
                    <li class="mono dim" style="font-size:0.78rem">
                      <strong>{c.id}</strong> — {c.source_path || c.document_id}
                      {#if c.line_start} L{c.line_start}–{c.line_end}{/if}
                    </li>
                  {/each}
                </ul>
              </details>
            {/if}
          </div>
        {/if}
        <div class="action-row" style="margin-top:1rem">
          <button class="btn-action btn-secondary" onclick={loadVendorDocList} disabled={vendorDocListLoading}>
            {vendorDocListLoading ? '…' : 'List Saved Docs'}
          </button>
        </div>
        {#if vendorDocList.length > 0}
          <table class="data-table" style="margin-top:0.5rem">
            <thead><tr><th>Doc Ref</th><th>Template</th><th>Title</th><th>§</th><th>Cit.</th></tr></thead>
            <tbody>
              {#each vendorDocList as d}
                <tr class="clickable-row" onclick={() => openVendorDoc(d.filename)}
                    class:expanded-row={vendorDocDetailFilename === d.filename}>
                  <td class="mono">{d.doc_ref}</td>
                  <td><span class="sev-badge sev-info">{d.template_id.replace(/_/g, ' ')}</span></td>
                  <td>{d.title.slice(0, 55)}{d.title.length > 55 ? '…' : ''}</td>
                  <td class="mono">{d.sections_count}</td>
                  <td class="mono">{d.citations_count}</td>
                </tr>
                {#if vendorDocDetailFilename === d.filename}
                  <tr class="detail-row">
                    <td colspan="5">
                      {#if vendorDocDetailLoading}
                        <p class="dim" style="padding:0.5rem">Loading…</p>
                      {:else if vendorDocDetail}
                        <div class="vd-output" style="margin:0;border-radius:0">
                          <div class="vd-doc-header">
                            <div>
                              <div class="vd-title">{vendorDocDetail.title}</div>
                              <div class="vd-meta">
                                <span class="vd-ref mono dim">{vendorDocDetail.doc_ref}</span>
                                <span class="vd-template-badge">{vendorDocDetail.template_id.replace(/_/g, ' ')}</span>
                              </div>
                            </div>
                            <div style="display:flex;gap:0.5rem;align-items:center">
                              <button class="btn-sm" onclick={downloadVendorDocJson}>↓ JSON</button>
                              <button class="btn-sm" onclick={downloadVendorDocMarkdown}>↓ Markdown</button>
                            </div>
                          </div>
                          {#if vendorDocDetail.scope_note}<p class="vd-scope-note">{vendorDocDetail.scope_note}</p>{/if}
                          {#each vendorDocDetail.sections as section}
                            <div class="vd-section">
                              <h4 class="vd-section-heading">{section.heading}</h4>
                              <p class="vd-section-content">{section.content}</p>
                            </div>
                          {/each}
                          {#if vendorDocDetail.citations.length > 0}
                            <details class="vd-citations">
                              <summary class="vd-cit-summary">Sources ({vendorDocDetail.citations.length})</summary>
                              <ul class="vd-cit-list">
                                {#each vendorDocDetail.citations as c}
                                  <li class="mono dim" style="font-size:0.78rem">
                                    <strong>{c.id}</strong> — {c.source_path || c.document_id}
                                    {#if c.line_start} L{c.line_start}–{c.line_end}{/if}
                                  </li>
                                {/each}
                              </ul>
                            </details>
                          {/if}
                        </div>
                      {/if}
                    </td>
                  </tr>
                {/if}
              {/each}
            </tbody>
          </table>
        {:else if !vendorDocListLoading}
          <p class="section-empty" style="margin-top:0.5rem">No saved docs — click List Saved Docs.</p>
        {/if}
      </section>
    {/if}

    <!-- ══════════════════════════════ MCP TAB ══════════════════════════════ -->
    {#if activeTab === 'mcp'}
      <section class="mcp-section">
        <div class="section-header">
          <h2>MCP Servers</h2>
          <button class="btn-refresh" onclick={loadMCPServers} disabled={mcpLoading}>↻</button>
        </div>
        {#if mcpError}
          <p class="section-error">{mcpError}</p>
        {:else if mcpLoading}
          <p class="section-empty">Loading…</p>
        {:else if mcpServers.length === 0}
          <p class="section-empty">Click ↻ to load MCP servers from mcp-config.yaml.</p>
        {:else}
          <table class="data-table">
            <thead><tr><th>ID</th><th>Transport</th><th>Enabled</th><th>Trust</th><th>Tools</th></tr></thead>
            <tbody>
              {#each mcpServers as s}
                <tr>
                  <td class="mono">{s.id}</td>
                  <td>{s.transport}</td>
                  <td>{s.enabled ? '✓' : '—'}</td>
                  <td>{s.trust}</td>
                  <td class="num">{s.tools.length}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </section>
    {/if}

    <!-- ══════════════════════════ ITERATION TAB ══════════════════════════ -->
    {#if activeTab === 'iteration' && modules.iteration !== false}
      <section class="iteration-section">
        <div class="iteration-header">
          <h2>Iteration History</h2>
          <button class="btn-refresh" onclick={refreshLineage} disabled={lineageLoading}>
            {lineageLoading ? '...' : '↻'}
          </button>
        </div>
        {#if lineageError}
          <p class="iteration-error">{lineageError}</p>
        {:else if lineages.length === 0 && !lineageLoading}
          <p class="iteration-empty">No skill lineage found. Run <code>opspilot iteration promote</code> to create one.</p>
        {:else}
          {#each lineages as skill}
            <div class="skill-block">
              <button class="skill-toggle" onclick={() => toggleSkill(skill.skill_name)}>
                <span class="skill-name">{skill.skill_name}</span>
                <span class="skill-count">{skill.versions.length} version{skill.versions.length !== 1 ? 's' : ''}</span>
                <span class="toggle-arrow">{expandedSkill[skill.skill_name] ? '▲' : '▼'}</span>
              </button>
              {#if expandedSkill[skill.skill_name]}
                <div class="lineage-tree">
                  {#each [...skill.versions].reverse() as v, i}
                    <div class="lineage-row {v.rolled_back ? 'rolled-back' : ''}">
                      <div class="lineage-version">
                        <span class="version-badge {v.rolled_back ? 'rolled-back-badge' : ''}">v{v.version}</span>
                        {#if v.rolled_back}<span class="rollback-flag">rolled back</span>{/if}
                      </div>
                      <div class="lineage-meta">
                        <span class="lineage-date">{v.promoted_at.slice(0, 10)}</span>
                        {#if v.iteration}
                          <span class="itr-id" title={v.iteration}>{v.iteration.slice(0, 16)}…</span>
                        {:else}
                          <span class="itr-id dim">manual</span>
                        {/if}
                        {#if v.promoted_variant_id}
                          <span class="variant-id" title={v.promoted_variant_id}>↑ {v.promoted_variant_id}</span>
                        {/if}
                      </div>
                      <div class="lineage-summary">{v.summary}</div>
                      {#if i < skill.versions.length - 1}
                        <div class="lineage-connector">│</div>
                      {/if}
                    </div>
                  {/each}
                </div>
              {/if}
            </div>
          {/each}
        {/if}
      </section>
    {/if}

    {#if activeTab === 'guide'}
      <section class="guide-section">

        <!-- Language switcher -->
        <div class="guide-lang-bar">
          <span class="guide-lang-label">Language</span>
          <div class="guide-lang-toggle">
            <button class="lang-btn {guideLang === 'zh' ? 'lang-btn-active' : ''}" onclick={() => guideLang = 'zh'}>中文</button>
            <button class="lang-btn {guideLang === 'en' ? 'lang-btn-active' : ''}" onclick={() => guideLang = 'en'}>EN</button>
          </div>
        </div>

        <!-- Architecture Diagram -->
        <div class="guide-block">
          <h2 class="guide-heading">{UI_STR[guideLang].arch} <span class="guide-hint">{UI_STR[guideLang].arch_hint}</span></h2>
          <div class="arch-diagram">

            <button
              class="arch-layer arch-layer-interface {selectedArch === 'interface' ? 'arch-selected' : ''}"
              onclick={() => selectedArch = selectedArch === 'interface' ? null : 'interface'}
            >
              <span class="arch-layer-label">Interface</span>
              <div class="arch-nodes">
                <div class="arch-node"><span class="arch-node-name">WebUI</span><span class="arch-node-sub">Svelte 5 · 8 tabs</span></div>
                <div class="arch-node"><span class="arch-node-name">TUI</span><span class="arch-node-sub">REPL shell</span></div>
                <div class="arch-node"><span class="arch-node-name">CLI</span><span class="arch-node-sub">opspilot harness</span></div>
              </div>
              <span class="arch-expand-hint">{selectedArch === 'interface' ? '▲' : '▼'}</span>
            </button>

            {#if selectedArch === 'interface'}
              <div class="arch-detail arch-detail-interface">
                <div class="arch-detail-header">{ARCH_DATA.interface[guideLang].title}</div>
                <p class="arch-detail-desc">{ARCH_DATA.interface[guideLang].desc}</p>
                <div class="arch-detail-items">
                  {#each ARCH_DATA.interface[guideLang].items as item}
                    <div class="arch-detail-item">
                      <div class="arch-detail-item-name">{item.name}{item.tech ? ` · ${item.tech}` : ''}</div>
                      <div class="arch-detail-item-desc">{item.desc}</div>
                    </div>
                  {/each}
                </div>
              </div>
            {/if}

            <div class="arch-connector">▼</div>

            <button
              class="arch-layer arch-layer-api {selectedArch === 'api' ? 'arch-selected' : ''}"
              onclick={() => selectedArch = selectedArch === 'api' ? null : 'api'}
            >
              <span class="arch-layer-label">API</span>
              <div class="arch-nodes">
                <div class="arch-node arch-node-wide">
                  <span class="arch-node-name">FastAPI + SSE streaming</span>
                  <span class="arch-node-sub">/run · /chat · /kb · /wiki · /vendordoc · /mcp · /iteration</span>
                </div>
              </div>
              <span class="arch-expand-hint">{selectedArch === 'api' ? '▲' : '▼'}</span>
            </button>

            {#if selectedArch === 'api'}
              <div class="arch-detail arch-detail-api">
                <div class="arch-detail-header">{ARCH_DATA.api[guideLang].title}</div>
                <p class="arch-detail-desc">{ARCH_DATA.api[guideLang].desc}</p>
                <div class="arch-detail-items">
                  {#each ARCH_DATA.api[guideLang].items as item}
                    <div class="arch-detail-item">
                      <div class="arch-detail-item-name">{item.name}</div>
                      <div class="arch-detail-item-desc">{item.desc}</div>
                    </div>
                  {/each}
                </div>
              </div>
            {/if}

            <div class="arch-connector">▼</div>

            <button
              class="arch-layer arch-layer-core {selectedArch === 'core' ? 'arch-selected' : ''}"
              onclick={() => selectedArch = selectedArch === 'core' ? null : 'core'}
            >
              <span class="arch-layer-label">Core</span>
              <div class="arch-nodes">
                <div class="arch-node"><span class="arch-node-name">Redactor</span><span class="arch-node-sub">PII · secret masking</span></div>
                <div class="arch-node arch-node-accent"><span class="arch-node-name">Orchestrator</span><span class="arch-node-sub">ReAct loop · tool dispatch</span></div>
                <div class="arch-node"><span class="arch-node-name">Evaluators</span><span class="arch-node-sub">golden test · scoring</span></div>
              </div>
              <span class="arch-expand-hint">{selectedArch === 'core' ? '▲' : '▼'}</span>
            </button>

            {#if selectedArch === 'core'}
              <div class="arch-detail arch-detail-core">
                <div class="arch-detail-header">{ARCH_DATA.core[guideLang].title}</div>
                <p class="arch-detail-desc">{ARCH_DATA.core[guideLang].desc}</p>
                <div class="arch-detail-items">
                  {#each ARCH_DATA.core[guideLang].items as item}
                    <div class="arch-detail-item">
                      <div class="arch-detail-item-name">{item.name}</div>
                      <div class="arch-detail-item-desc">{item.desc}</div>
                    </div>
                  {/each}
                </div>
              </div>
            {/if}

            <div class="arch-connector">▼</div>

            <div class="arch-bottom-row">
              <button
                class="arch-layer arch-layer-storage {selectedArch === 'storage' ? 'arch-selected' : ''}"
                onclick={() => selectedArch = selectedArch === 'storage' ? null : 'storage'}
              >
                <span class="arch-layer-label">Storage</span>
                <div class="arch-nodes arch-nodes-col">
                  <span class="arch-pill">ChromaDB · vector KB</span>
                  <span class="arch-pill">SQLite · sessions</span>
                  <span class="arch-pill">Playbooks · YAML</span>
                </div>
                <span class="arch-expand-hint">{selectedArch === 'storage' ? '▲' : '▼'}</span>
              </button>
              <button
                class="arch-layer arch-layer-external {selectedArch === 'external' ? 'arch-selected' : ''}"
                onclick={() => selectedArch = selectedArch === 'external' ? null : 'external'}
              >
                <span class="arch-layer-label">External</span>
                <div class="arch-nodes arch-nodes-col">
                  <span class="arch-pill">Claude · Gemini · OpenRouter</span>
                  <span class="arch-pill">MCP Servers (stdio / HTTP)</span>
                  <span class="arch-pill">Ollama · local models</span>
                </div>
                <span class="arch-expand-hint">{selectedArch === 'external' ? '▲' : '▼'}</span>
              </button>
            </div>

            {#if selectedArch === 'storage' || selectedArch === 'external'}
              {@const key = selectedArch as 'storage' | 'external'}
              <div class="arch-detail arch-detail-{key}">
                <div class="arch-detail-header">{ARCH_DATA[key][guideLang].title}</div>
                <p class="arch-detail-desc">{ARCH_DATA[key][guideLang].desc}</p>
                <div class="arch-detail-items">
                  {#each ARCH_DATA[key][guideLang].items as item}
                    <div class="arch-detail-item">
                      <div class="arch-detail-item-name">{item.name}{item.tech ? ` · ${item.tech}` : ''}</div>
                      <div class="arch-detail-item-desc">{item.desc}</div>
                    </div>
                  {/each}
                </div>
              </div>
            {/if}

          </div>
        </div>

        <!-- Workflow -->
        <div class="guide-block">
          <h2 class="guide-heading">{UI_STR[guideLang].wf} <span class="guide-hint">{UI_STR[guideLang].wf_hint}</span></h2>
          <div class="wf-pipeline">
            {#each WF_STEPS[guideLang] as step, i}
              {#if i > 0}<div class="wf-arr">→</div>{/if}
              <button
                class="wf-step {step.accent ? 'wf-step-highlight' : ''} {selectedStep === step.n ? 'wf-step-selected' : ''}"
                onclick={() => selectedStep = selectedStep === step.n ? null : step.n}
              >
                <div class="wf-num">{step.n}</div>
                <div class="wf-body">
                  <div class="wf-name">{step.name}</div>
                  <div class="wf-desc">{step.desc}</div>
                </div>
              </button>
            {/each}
          </div>

          {#if selectedStep !== null}
            {@const d = WF_DATA[selectedStep][guideLang]}
            <div class="wf-detail">
              <div class="wf-detail-header">{d.title}</div>
              <p class="wf-detail-desc">{d.desc}</p>
              <div class="wf-detail-items">
                {#each d.items as item}
                  <div class="wf-detail-item">
                    <span class="wf-detail-item-name">{item.name}</span>
                    <span class="wf-detail-item-desc">{item.desc}</span>
                  </div>
                {/each}
              </div>
            </div>
          {:else}
            <div class="wf-inner">
              <span class="wf-inner-label">{UI_STR[guideLang].orch_inner}</span>
              <span class="wf-badge wf-badge-red">Redact</span>
              <span class="wf-inner-sep">→</span>
              <span class="wf-badge wf-badge-blue">KB Search</span>
              <span class="wf-inner-sep">→</span>
              <span class="wf-badge wf-badge-green">MCP Tools</span>
              <span class="wf-inner-sep">→</span>
              <span class="wf-badge wf-badge-primary">LLM</span>
              <span class="wf-inner-sep">→</span>
              <span class="wf-badge wf-badge-amber">Evaluator</span>
            </div>
          {/if}
        </div>

        <!-- Feature Grid -->
        <div class="guide-block">
          <h2 class="guide-heading">{UI_STR[guideLang].feat} <span class="guide-hint">{UI_STR[guideLang].feat_hint}</span></h2>
          <div class="feat-grid">
            {#each FEAT_CARDS[guideLang] as card}
              <button
                class="feat-card feat-card-{card.accent} {expandedFeat === card.key ? 'feat-card-open' : ''}"
                onclick={() => expandedFeat = expandedFeat === card.key ? null : card.key}
              >
                <div class="feat-card-top">
                  <div class="feat-title">{card.title}</div>
                  <span class="feat-toggle">{expandedFeat === card.key ? '▲' : '▼'}</span>
                </div>
                <ul class="feat-list">
                  {#each card.items as item}
                    <li>{item}</li>
                  {/each}
                </ul>
                {#if expandedFeat === card.key}
                  <div class="feat-specs">
                    <div class="feat-specs-title">{UI_STR[guideLang].tech_specs}</div>
                    <div class="feat-specs-grid">
                      {#each FEAT_EXTRA[card.key][guideLang].items as spec}
                        <span class="feat-spec-label">{spec.label}</span>
                        <span class="feat-spec-val">{spec.val}</span>
                      {/each}
                    </div>
                  </div>
                {/if}
              </button>
            {/each}
          </div>
        </div>

      </section>
    {/if}

  </main>
</div>

<style>
  .app {
    max-width: 960px;
    margin: 0 auto;
    padding: 1.5rem;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1rem;
    border-bottom: 2px solid var(--border);
    padding-bottom: 0.75rem;
  }

  header h1 {
    font-size: 1.8rem;
    color: var(--primary);
  }

  .model-ref {
    font-family: 'Courier New', Courier, monospace;
    font-size: 0.8rem;
    background: var(--primary-bg);
    color: var(--primary);
    padding: 0.25rem 0.6rem;
    border-radius: 4px;
    border: 1px solid var(--primary-border);
  }

  .model-select {
    font-family: 'Courier New', Courier, monospace;
    font-size: 0.8rem;
    background: var(--primary-bg);
    color: var(--primary);
    padding: 0.25rem 0.6rem;
    border-radius: 4px;
    border: 1px solid var(--primary-border);
    cursor: pointer;
  }

  .model-select:disabled { opacity: 0.6; cursor: not-allowed; }

  .theme-toggle {
    background: none;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    padding: 0.25rem 0.55rem;
    font-size: 1rem;
    color: var(--text-muted);
    line-height: 1;
    cursor: pointer;
    margin-left: 0.5rem;
  }

  .theme-toggle:hover { background: var(--bg-muted); color: var(--text); }

  /* ── Tab Navigation ── */
  .tab-nav {
    display: flex;
    gap: 0.25rem;
    border-bottom: 2px solid var(--border);
    margin-bottom: 1.5rem;
    flex-wrap: wrap;
  }

  .nav-tab {
    padding: 0.5rem 1rem;
    font-size: 0.9rem;
    font-weight: 500;
    color: var(--text-muted);
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s;
  }

  .nav-tab:hover { color: var(--text); }

  .nav-tab.active {
    color: var(--primary);
    border-bottom-color: var(--primary);
    font-weight: 600;
  }

  /* ── Input Section ── */
  .input-section { margin-bottom: 1.5rem; }

  .input-section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.75rem;
  }

  .input-section-header h2 {
    font-size: 1.1rem;
    color: var(--text);
    margin: 0;
  }

  .mode-toggle {
    display: flex;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    overflow: hidden;
  }

  .mode-btn {
    padding: 0.25rem 0.75rem;
    font-size: 0.8rem;
    background: var(--bg-subtle);
    color: var(--text-muted);
    border: none;
    cursor: pointer;
  }

  .mode-btn.active {
    background: var(--primary);
    color: #fff;
    font-weight: 600;
  }

  .mode-btn:not(.active):hover { background: var(--bg-muted); }

  textarea {
    width: 100%;
    padding: 0.75rem;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--bg-surface);
    margin-bottom: 0.75rem;
    font-size: 0.9rem;
    color: var(--text);
    resize: vertical;
  }

  .nl-textarea { font-size: 1rem; line-height: 1.6; }

  .run-row { display: flex; align-items: center; gap: 1rem; }

  .btn-run {
    padding: 0.6rem 1.5rem;
    background: var(--primary);
    color: #fff;
    border: none;
    border-radius: 6px;
    font-size: 1rem;
    font-weight: 600;
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    cursor: pointer;
  }

  .btn-run:disabled { opacity: 0.6; cursor: not-allowed; }

  .usage-badge {
    font-family: 'Courier New', Courier, monospace;
    font-size: 0.78rem;
    color: var(--text-muted);
    background: var(--bg-muted);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0.2rem 0.6rem;
    white-space: nowrap;
  }

  .spinner {
    display: inline-block;
    width: 14px;
    height: 14px;
    border: 2px solid rgba(255, 255, 255, 0.4);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .status-log {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px 14px;
    margin-bottom: 12px;
    font-family: monospace;
    font-size: 0.82rem;
  }

  .status-line { color: var(--text-muted, #888); line-height: 1.6; }
  .status-line--active { animation: blink 1s step-start infinite; }
  @keyframes blink { 50% { opacity: 0; } }

  .error-banner {
    background: var(--error-bg);
    color: var(--error-text);
    border: 1px solid var(--error-border);
    border-radius: 6px;
    padding: 0.75rem 1rem;
    margin-bottom: 1rem;
  }

  .cards {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
    margin-bottom: 1.5rem;
  }

  @media (max-width: 640px) { .cards { grid-template-columns: 1fr; } }

  .card {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.75rem;
  }

  .card-header h3 {
    font-size: 0.95rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
  }

  .btn-copy {
    font-size: 0.75rem;
    padding: 0.2rem 0.6rem;
    background: var(--bg-muted);
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    color: var(--text-sub);
    cursor: pointer;
  }

  .btn-copy:hover { background: var(--bg-hover); }

  .card ul, .card ol { margin: 0; padding-left: 1.25rem; }
  .card li { margin-bottom: 0.4rem; font-size: 0.95rem; }
  .rationale { margin: 0.2rem 0 0.6rem; color: var(--text-muted); font-size: 0.88rem; }

  .severity-badge {
    display: inline-block;
    padding: 0.3rem 0.8rem;
    border-radius: 9999px;
    font-weight: 700;
    font-size: 1.1rem;
    background: var(--warn-bg);
    color: var(--warn-text);
    border: 1px solid var(--warn-border);
  }

  .tier-badge {
    display: inline-block;
    margin-right: 0.4rem;
    padding: 0.05rem 0.45rem;
    border-radius: 9999px;
    font-weight: 700;
    font-size: 0.75rem;
    vertical-align: middle;
    border: 1px solid var(--border);
    color: var(--text-muted);
  }
  .tier-badge.tier-L1 { background: #e6f4ea; color: #1e7e34; border-color: #b7dfc2; }
  .tier-badge.tier-L2 { background: #fff4e5; color: #b26a00; border-color: #f0d2a0; }
  .tier-badge.tier-L3 { background: #fde8e8; color: #b02a37; border-color: #f2c0c4; }

  .wi-badge {
    display: inline-block;
    padding: 0.05rem 0.45rem;
    border-radius: 9999px;
    font-weight: 700;
    font-size: 0.8rem;
    background: var(--accent-bg, #e8f0fe);
    color: var(--accent-text, #1a56db);
    border: 1px solid var(--border);
  }
  .confirm-banner {
    margin: 0.75rem 0;
    padding: 0.75rem 1rem;
    border-radius: 0.5rem;
    background: var(--warn-bg);
    border: 1px solid var(--warn-border);
  }
  .confirm-banner p { margin: 0 0 0.6rem; }
  .confirm-actions { display: flex; gap: 0.5rem; }
  .btn-confirm {
    padding: 0.4rem 0.9rem;
    border-radius: 0.4rem;
    border: 1px solid var(--border);
    background: var(--surface, #fff);
    cursor: pointer;
    font-weight: 600;
  }
  .btn-confirm:hover { background: var(--accent-bg, #e8f0fe); }
  .classified-note { margin: 0.5rem 0; color: var(--text-muted); font-size: 0.9rem; }

  .wi-type-label {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.85rem;
    color: var(--text-muted);
  }
  .wi-type-select {
    padding: 0.4rem 0.6rem;
    border-radius: 0.4rem;
    border: 1px solid var(--border);
    background: var(--surface, #fff);
    font-size: 0.9rem;
  }

  .escalation { margin-top: 0.5rem; font-size: 0.9rem; color: var(--warn-text2); }

  /* ── History ── */
  .history-section {
    margin-top: 2rem;
    border-top: 1px solid var(--border);
    padding-top: 1.5rem;
  }

  .history-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 1rem;
  }

  .history-header h2 { font-size: 1.1rem; color: var(--text); margin: 0; }

  .btn-refresh {
    background: none;
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    padding: 0.15rem 0.5rem;
    font-size: 1rem;
    color: var(--text-muted);
    line-height: 1;
    cursor: pointer;
  }

  .btn-refresh:hover { background: var(--bg-muted); }

  .history-empty { color: var(--text-faint); font-size: 0.9rem; }

  .history-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }

  .history-table th {
    text-align: left;
    padding: 0.4rem 0.75rem;
    color: var(--text-muted);
    font-weight: 600;
    border-bottom: 1px solid var(--border);
  }

  .history-table td {
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--border-faint);
    vertical-align: middle;
  }

  .col-time { color: var(--text-sub); white-space: nowrap; }

  .status-badge {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
  }

  .status-archived { background: var(--success-bg); color: var(--success-text); }
  .status-aborted { background: var(--error-bg); color: var(--error-text); }
  .status-active { background: var(--sev-medium-bg); color: var(--warn-text); }

  .btn-view {
    font-size: 0.8rem;
    padding: 0.2rem 0.6rem;
    background: var(--bg-muted);
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    color: var(--primary);
    cursor: pointer;
  }

  .btn-view:hover { background: var(--bg-hover); }

  .expanded-row td { padding: 0.75rem; background: var(--bg-subtle); border-bottom: 2px solid var(--border); }
  .clickable-row { cursor: pointer; }
  .clickable-row:hover td { background: var(--bg-hover); }
  .detail-row td { padding: 0; background: var(--bg-subtle); border-bottom: 2px solid var(--border-strong); }

  .col-sid { font-family: 'Courier New', monospace; font-size: 0.78rem; color: var(--text-muted); white-space: nowrap; }

  .session-detail { padding: 0.75rem 1.25rem 1rem; }
  .session-detail-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; font-size: 0.82rem; }

  /* ── Chat ── */
  .chat-section {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 200px);
    min-height: 400px;
  }

  .chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 1rem 0;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .chat-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-muted);
    text-align: center;
    gap: 1rem;
  }

  .chat-suggestions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    justify-content: center;
    margin-top: 0.5rem;
  }

  .suggestion-btn {
    padding: 0.4rem 0.9rem;
    font-size: 0.85rem;
    background: var(--bg-subtle);
    border: 1px solid var(--border-strong);
    border-radius: 9999px;
    color: var(--primary);
    cursor: pointer;
  }

  .suggestion-btn:hover { background: var(--bg-muted); }

  .chat-bubble {
    display: flex;
    max-width: 80%;
  }

  .chat-bubble.user {
    align-self: flex-end;
    flex-direction: row-reverse;
  }

  .chat-bubble.assistant { align-self: flex-start; }

  .bubble-content {
    padding: 0.65rem 0.9rem;
    border-radius: 12px;
    font-size: 0.95rem;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .chat-bubble.user .bubble-content {
    background: var(--primary);
    color: #fff;
    border-bottom-right-radius: 3px;
  }

  .chat-bubble.assistant .bubble-content {
    background: var(--bg-subtle);
    color: var(--text);
    border: 1px solid var(--border);
    border-bottom-left-radius: 3px;
  }

  .chat-thinking { color: var(--text-muted); font-style: italic; }

  .chat-input-row {
    display: flex;
    gap: 0.5rem;
    align-items: flex-end;
    margin-top: 1rem;
    border-top: 1px solid var(--border);
    padding-top: 1rem;
  }

  .chat-input {
    flex: 1;
    margin: 0;
    resize: none;
    border-radius: 8px;
  }

  .btn-chat-send {
    width: 42px;
    height: 42px;
    background: var(--primary);
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: 1.1rem;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    flex-shrink: 0;
  }

  .btn-chat-send:disabled { opacity: 0.5; cursor: not-allowed; }

  .chat-footer {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 0 0;
    min-height: 1.5rem;
  }

  /* ── KB, Wiki, Sections ── */
  .kb-section, .wiki-section, .mcp-section, .vendordoc-section, .iteration-section {
    padding-top: 0.5rem;
  }

  .section-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 1rem;
  }

  .section-header h2 { font-size: 1.1rem; color: var(--text); margin: 0; flex: 1; }

  .section-tabs { display: flex; gap: 0.25rem; }

  .tab-btn {
    font-size: 0.8rem;
    padding: 0.2rem 0.7rem;
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    background: var(--bg-subtle);
    color: var(--text-sub);
    cursor: pointer;
  }

  .tab-btn.active { background: var(--primary); color: #fff; border-color: var(--primary); }

  .section-empty { color: var(--text-faint); font-size: 0.9rem; }
  .section-error { color: var(--error-text); font-size: 0.9rem; }
  .section-ok { color: var(--success-text); font-size: 0.9rem; }

  .data-table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
  .data-table th { text-align: left; padding: 0.35rem 0.65rem; color: var(--text-muted); font-weight: 600; border-bottom: 1px solid var(--border); }
  .data-table td { padding: 0.4rem 0.65rem; border-bottom: 1px solid var(--border-faint); vertical-align: top; }

  .mono { font-family: 'Courier New', monospace; font-size: 0.82rem; }
  .num { text-align: right; font-family: 'Courier New', monospace; }
  .dim { color: var(--text-faint); }

  .snippet { color: var(--text-sub); font-size: 0.82rem; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .search-row { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
  .search-input { flex: 1; padding: 0.45rem 0.75rem; border: 1px solid var(--border-strong); border-radius: 6px; font-size: 0.9rem; }

  .action-row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; align-items: center; }
  .short-input { padding: 0.4rem 0.7rem; border: 1px solid var(--border-strong); border-radius: 6px; font-size: 0.85rem; width: 200px; }

  .btn-action {
    padding: 0.4rem 1rem;
    background: var(--primary);
    color: #fff;
    border: none;
    border-radius: 6px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
  }

  .btn-action:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-action.btn-secondary { background: var(--bg-muted); color: var(--primary); border: 1px solid var(--border-strong); }

  .btn-sm {
    font-size: 0.75rem;
    padding: 0.15rem 0.5rem;
    background: var(--bg-muted);
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    color: var(--primary);
    cursor: pointer;
  }

  .sev-badge { font-size: 0.72rem; font-weight: 700; padding: 0.1rem 0.4rem; border-radius: 3px; }
  .sev-critical { background: var(--error-bg); color: var(--error-text); }
  .sev-high { background: var(--sev-high-bg); color: var(--sev-high-text); }
  .sev-medium { background: var(--sev-medium-bg); color: var(--warn-text); }
  .sev-low { background: var(--success-bg); color: var(--success-text); }
  .sev-ok { background: var(--success-bg); color: var(--success-text); }
  .sev-warn { background: var(--warn-bg); color: var(--warn-text); }
  .sev-info { background: var(--info-bg); color: var(--info-text); }

  /* ── Conflicts ── */
  .conflict-badge {
    display: inline-flex; align-items: center; justify-content: center;
    min-width: 16px; height: 16px; padding: 0 4px;
    background: var(--error-badge); color: #fff; border-radius: 9999px;
    font-size: 0.65rem; font-weight: 700; margin-left: 4px; vertical-align: middle;
  }

  .conflict-toolbar { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; }
  .filter-label { font-size: 0.85rem; color: var(--text-sub); display: flex; align-items: center; gap: 0.4rem; }
  .filter-label select { font-size: 0.85rem; padding: 0.2rem 0.5rem; border: 1px solid var(--border-strong); border-radius: 4px; }
  .conflict-table td { vertical-align: top; padding: 0.5rem 0.65rem; }
  .conflict-doc { font-size: 0.85rem; font-weight: 500; color: var(--text); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chunk-preview { font-size: 0.75rem; color: var(--text-muted); margin-top: 0.2rem; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .conflict-type-badge { font-size: 0.72rem; font-weight: 600; padding: 0.1rem 0.45rem; border-radius: 3px; white-space: nowrap; }
  .ctype-temporal_supersede { background: var(--info-bg); color: var(--info-text); }
  .ctype-direct_contradiction { background: var(--error-bg); color: var(--error-text); }
  .ctype-scope_overlap { background: var(--sev-medium-bg); color: var(--warn-text); }
  .resolve-btns { display: flex; flex-direction: column; gap: 0.3rem; }
  .btn-a-wins { background: var(--success-bg); color: var(--success-text); border-color: var(--success-border); }
  .btn-b-wins { background: var(--info-bg); color: var(--info-text); border-color: var(--info-border); }
  .row-conflict { background: var(--row-conflict-bg); }
  .warn-badge { display: inline-block; margin-left: 4px; color: var(--warn-text2); font-size: 0.85rem; cursor: help; }

  .status-open { background: var(--warn-bg); color: var(--warn-text); }
  .status-a_wins { background: var(--success-bg); color: var(--success-text); }
  .status-b_wins { background: var(--info-bg); color: var(--info-text); }
  .status-merged { background: var(--status-merged-bg); color: var(--status-merged-text); }
  .status-dismissed { background: var(--bg-muted); color: var(--text-muted); }

  .kb-stats-bar {
    display: flex; align-items: center; gap: 8px;
    padding: 6px 10px; background: var(--bg-subtle); border: 1px solid var(--border);
    border-radius: 6px; font-size: 0.8rem; color: var(--text-sub); margin-bottom: 10px;
  }
  .stat-item strong { color: var(--text); }
  .stat-sep { color: var(--border-strong); }
  .stat-warn strong { color: var(--warn-text2); }

  .corr-badge {
    display: inline-block; background: var(--info-bg); color: var(--info-text);
    border-radius: 10px; font-size: 0.7rem; padding: 0 6px; margin-left: 4px;
    font-weight: 600; line-height: 1.6;
  }

  .btn-correct-toggle {
    background: none; border: 1px solid var(--border-strong); border-radius: 4px;
    cursor: pointer; padding: 1px 6px; font-size: 0.85rem; color: var(--text-sub);
  }
  .btn-correct-toggle:hover { background: var(--bg-muted); }

  .correct-row td { background: var(--bg-subtle); padding: 8px 12px; }
  .correct-form { display: flex; flex-direction: column; gap: 8px; max-width: 700px; }
  .correct-label { display: flex; flex-direction: column; gap: 4px; font-size: 0.8rem; color: var(--text-muted); }
  .correct-input { padding: 4px 8px; border: 1px solid var(--border); border-radius: 4px; font-size: 0.85rem; }
  .correct-textarea { padding: 6px 8px; border: 1px solid var(--border); border-radius: 4px; font-size: 0.8rem; font-family: monospace; resize: vertical; }
  .correct-actions { display: flex; gap: 8px; }
  .btn-secondary { padding: 4px 10px; background: var(--bg-muted); border: 1px solid var(--border-strong); border-radius: 4px; cursor: pointer; font-size: 0.8rem; }

  /* ── Wiki ── */
  .wiki-detail { padding: 1rem 1.25rem; }
  .wiki-detail-summary { margin: 0 0 0.5rem; font-style: italic; }
  .wiki-detail-tags { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-bottom: 0.75rem; }
  .wiki-detail-body {
    margin: 0; padding: 0.75rem 1rem; background: var(--bg-surface);
    border: 1px solid var(--border); border-radius: 6px; font-size: 0.82rem;
    line-height: 1.6; white-space: pre-wrap; word-break: break-word;
    max-height: 480px; overflow-y: auto; font-family: 'Courier New', monospace; color: var(--text);
  }

  /* ── Vendor Doc ── */
  .vd-form { display: flex; flex-direction: column; gap: 0.75rem; margin-bottom: 1rem; }
  .vd-row { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: flex-end; }
  .vd-label { display: flex; flex-direction: column; gap: 4px; font-size: 0.8rem; color: var(--text-muted); flex: 1; min-width: 180px; }
  .vd-input { padding: 0.4rem 0.7rem; border: 1px solid var(--border-strong); border-radius: 6px; font-size: 0.9rem; background: var(--bg-surface); color: var(--text); }
  .vd-input-sm { min-width: 140px; max-width: 200px; }
  .vd-select { padding: 0.4rem 0.7rem; border: 1px solid var(--border-strong); border-radius: 6px; font-size: 0.9rem; background: var(--bg-surface); color: var(--text); }
  .vd-actions { display: flex; align-items: center; gap: 1rem; }
  .vd-output { margin-top: 1rem; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  .vd-doc-header { padding: 1rem 1.25rem 0.75rem; background: var(--bg-subtle); border-bottom: 1px solid var(--border); display: flex; align-items: flex-start; justify-content: space-between; }
  .vd-title { font-size: 1.1rem; font-weight: 700; color: var(--text); margin-bottom: 0.3rem; }
  .vd-meta { display: flex; align-items: center; gap: 0.6rem; }
  .vd-template-badge { font-size: 0.72rem; font-weight: 600; background: var(--info-bg); color: var(--info-text); border-radius: 3px; padding: 0.1rem 0.45rem; text-transform: capitalize; }
  .vd-scope-note { font-size: 0.85rem; color: var(--text-sub); font-style: italic; padding: 0.5rem 1.25rem 0; margin: 0; }
  .vd-section { padding: 0.75rem 1.25rem; border-bottom: 1px solid var(--border-faint); }
  .vd-section:last-of-type { border-bottom: none; }
  .vd-section-heading { font-size: 0.9rem; font-weight: 700; color: var(--text); margin: 0 0 0.4rem; }
  .vd-section-content { font-size: 0.88rem; color: var(--text); margin: 0; line-height: 1.6; white-space: pre-wrap; }
  .vd-section-cits { display: flex; gap: 0.35rem; flex-wrap: wrap; margin-top: 0.4rem; }
  .vd-cit-tag { font-size: 0.7rem; background: var(--primary-bg); color: var(--primary); border: 1px solid var(--primary-border); border-radius: 3px; padding: 0 0.4rem; }
  .vd-citations { padding: 0.6rem 1.25rem; background: var(--bg-subtle); }
  .vd-cit-summary { font-size: 0.8rem; color: var(--text-muted); cursor: pointer; }
  .vd-cit-list { margin: 0.4rem 0 0; padding-left: 1rem; display: flex; flex-direction: column; gap: 0.2rem; list-style: disc; }
  .vd-ref { font-size: 0.78rem; }

  /* ── Iteration ── */
  .iteration-header { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; }
  .iteration-header h2 { font-size: 1.1rem; color: var(--text); margin: 0; }
  .iteration-empty, .iteration-error { color: var(--text-faint); font-size: 0.9rem; }
  .iteration-error { color: var(--error-text); }

  .skill-block { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 0.75rem; overflow: hidden; }
  .skill-toggle { width: 100%; display: flex; align-items: center; gap: 0.75rem; padding: 0.65rem 1rem; background: var(--bg-subtle); border: none; cursor: pointer; text-align: left; font-size: 0.95rem; }
  .skill-toggle:hover { background: var(--bg-muted); }
  .skill-name { font-family: 'Courier New', monospace; font-weight: 600; color: var(--primary); flex: 1; }
  .skill-count { font-size: 0.8rem; color: var(--text-muted); }
  .toggle-arrow { color: var(--text-faint); font-size: 0.8rem; }

  .lineage-tree { padding: 0.75rem 1rem; background: var(--bg-surface); }
  .lineage-row { padding: 0.5rem 0; border-left: 2px solid var(--border-strong); padding-left: 1rem; margin-left: 0.5rem; }
  .lineage-row.rolled-back { opacity: 0.55; }
  .lineage-version { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.2rem; }
  .version-badge { font-family: 'Courier New', monospace; font-size: 0.82rem; font-weight: 700; background: var(--info-bg); color: var(--info-text); padding: 0.1rem 0.5rem; border-radius: 4px; }
  .version-badge.rolled-back-badge { background: var(--error-bg); color: var(--error-text); }
  .rollback-flag { font-size: 0.72rem; color: var(--error-text); background: var(--error-bg); padding: 0.1rem 0.4rem; border-radius: 3px; }
  .lineage-meta { display: flex; align-items: center; gap: 0.6rem; font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.2rem; }
  .lineage-date { font-family: 'Courier New', monospace; }
  .itr-id { font-family: 'Courier New', monospace; background: var(--bg-muted); padding: 0.05rem 0.35rem; border-radius: 3px; }
  .itr-id.dim { color: var(--text-faint); }
  .variant-id { font-family: 'Courier New', monospace; color: var(--success-text); font-size: 0.75rem; }
  .lineage-summary { font-size: 0.88rem; color: var(--text); line-height: 1.4; }
  .lineage-connector { color: var(--border-strong); padding-left: 1rem; margin-left: 0.5rem; font-size: 0.9rem; }

  /* ── Guide Tab ── */
  .guide-section { display: flex; flex-direction: column; gap: 1.5rem; }

  .guide-lang-bar {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 0.6rem;
  }

  .guide-lang-label {
    font-size: 0.72rem;
    color: var(--text-faint);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: 500;
  }

  .guide-lang-toggle {
    display: flex;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    overflow: hidden;
  }

  .lang-btn {
    padding: 0.25rem 0.7rem;
    font-size: 0.75rem;
    font-weight: 600;
    border: none;
    background: none;
    color: var(--text-muted);
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
    font-family: inherit;
  }

  .lang-btn + .lang-btn { border-left: 1px solid var(--border-strong); }

  .lang-btn:hover { background: var(--bg-muted); color: var(--text); }

  .lang-btn-active {
    background: var(--primary);
    color: #fff;
  }

  .lang-btn-active:hover { background: var(--primary); color: #fff; }

  .guide-block {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1.5rem 1.75rem;
  }

  .guide-heading {
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin: 0 0 1.25rem 0;
    padding-bottom: 0.6rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 0.6rem;
  }

  .guide-hint {
    font-size: 0.68rem;
    font-weight: 400;
    letter-spacing: 0;
    text-transform: none;
    color: var(--text-faint);
    font-style: italic;
  }

  /* ── Architecture Diagram ── */
  .arch-diagram { display: flex; flex-direction: column; gap: 0; }

  .arch-layer {
    display: flex;
    align-items: stretch;
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
    cursor: pointer;
    text-align: left;
    width: 100%;
    background: none;
    font-family: inherit;
    transition: box-shadow 0.15s, border-color 0.15s;
    position: relative;
  }

  .arch-layer:hover { box-shadow: 0 0 0 2px var(--border-strong); }
  .arch-selected { box-shadow: 0 0 0 2px var(--primary) !important; }

  .arch-expand-hint {
    font-size: 0.65rem;
    color: var(--text-faint);
    padding: 0.5rem 0.6rem;
    align-self: center;
    flex-shrink: 0;
  }

  .arch-layer-label {
    writing-mode: vertical-lr;
    transform: rotate(180deg);
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 0.75rem 0.5rem;
    min-width: 1.9rem;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .arch-nodes {
    display: flex;
    flex-wrap: wrap;
    gap: 0.55rem;
    padding: 0.7rem;
    flex: 1;
    align-items: center;
  }

  .arch-nodes-col { flex-direction: column; align-items: flex-start; gap: 0.3rem; }

  .arch-node {
    display: flex;
    flex-direction: column;
    gap: 0.08rem;
    background: var(--bg-muted);
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    padding: 0.4rem 0.7rem;
  }

  .arch-node-wide { flex: 1; }

  .arch-node-accent {
    border-color: var(--primary-border);
    background: var(--primary-bg);
  }

  .arch-node-name {
    font-size: 0.82rem;
    font-weight: 700;
    color: var(--text);
    font-family: 'Courier New', monospace;
  }

  .arch-node-sub { font-size: 0.7rem; color: var(--text-muted); }
  .arch-node-accent .arch-node-name { color: var(--primary); }

  .arch-pill {
    font-size: 0.73rem;
    color: var(--text-sub);
    background: var(--bg-muted);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0.18rem 0.5rem;
  }

  .arch-connector {
    text-align: center;
    color: var(--text-faint);
    font-size: 0.75rem;
    padding: 0.15rem 0;
  }

  .arch-bottom-row { display: flex; gap: 0.6rem; }
  .arch-bottom-row .arch-layer { flex: 1; }

  /* Layer accents */
  .arch-layer-interface { border-color: var(--primary-border); }
  .arch-layer-interface .arch-layer-label { background: var(--primary-bg); color: var(--primary); border-right: 1px solid var(--primary-border); }
  .arch-layer-api { border-color: var(--info-border); }
  .arch-layer-api .arch-layer-label { background: var(--info-bg); color: var(--info-text); border-right: 1px solid var(--info-border); }
  .arch-layer-core { border-color: var(--warn-border); }
  .arch-layer-core .arch-layer-label { background: var(--warn-bg); color: var(--warn-text); border-right: 1px solid var(--warn-border); }
  .arch-layer-storage { border-color: var(--success-border); }
  .arch-layer-storage .arch-layer-label { background: var(--success-bg); color: var(--success-text); border-right: 1px solid var(--success-border); }
  .arch-layer-external { border-color: var(--border-strong); }
  .arch-layer-external .arch-layer-label { background: var(--bg-muted); color: var(--text-muted); border-right: 1px solid var(--border-strong); }

  /* Detail panels */
  .arch-detail {
    border-radius: 8px;
    border: 1px solid var(--border);
    padding: 1rem 1.1rem;
    background: var(--bg-muted);
    margin-top: 0.3rem;
    animation: fadeSlide 0.15s ease;
  }

  .arch-detail-interface { border-left: 3px solid var(--primary); }
  .arch-detail-api       { border-left: 3px solid var(--info-text); }
  .arch-detail-core      { border-left: 3px solid var(--warn-text); }
  .arch-detail-storage   { border-left: 3px solid var(--success-text); }
  .arch-detail-external  { border-left: 3px solid var(--border-strong); }

  .arch-detail-header {
    font-size: 0.82rem;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 0.4rem;
  }

  .arch-detail-desc {
    font-size: 0.8rem;
    color: var(--text-muted);
    margin: 0 0 0.75rem 0;
    line-height: 1.5;
  }

  .arch-detail-items { display: flex; flex-direction: column; gap: 0.5rem; }

  .arch-detail-item {
    display: grid;
    grid-template-columns: 1fr 2fr;
    gap: 0.5rem;
    align-items: baseline;
    font-size: 0.79rem;
    padding: 0.4rem 0;
    border-top: 1px solid var(--border);
  }

  .arch-detail-item:first-child { border-top: none; }

  .arch-detail-item-name {
    font-weight: 600;
    color: var(--text);
    font-family: 'Courier New', monospace;
    font-size: 0.77rem;
  }

  .arch-detail-item-desc { color: var(--text-muted); line-height: 1.45; }

  /* ── Workflow ── */
  .wf-pipeline {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    flex-wrap: wrap;
    margin-bottom: 0.8rem;
  }

  .wf-step {
    display: flex;
    align-items: center;
    gap: 0.55rem;
    padding: 0.5rem 0.85rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--bg-muted);
    flex: 1;
    min-width: 120px;
    cursor: pointer;
    font-family: inherit;
    text-align: left;
    transition: box-shadow 0.15s, border-color 0.15s;
  }

  .wf-step:hover { box-shadow: 0 0 0 2px var(--border-strong); }

  .wf-step-highlight { border-color: var(--primary-border); background: var(--primary-bg); }
  .wf-step-selected { box-shadow: 0 0 0 2px var(--primary) !important; }

  .wf-num {
    width: 1.45rem;
    height: 1.45rem;
    border-radius: 50%;
    background: var(--border-strong);
    color: var(--text);
    font-size: 0.7rem;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .wf-step-highlight .wf-num { background: var(--primary); color: #fff; }
  .wf-step-selected .wf-num  { background: var(--primary); color: #fff; }

  .wf-name { font-size: 0.8rem; font-weight: 700; color: var(--text); font-family: 'Courier New', monospace; }
  .wf-desc { font-size: 0.69rem; color: var(--text-muted); }
  .wf-arr  { color: var(--text-faint); font-size: 0.9rem; flex-shrink: 0; }

  /* Workflow detail panel */
  .wf-detail {
    border-radius: 8px;
    border: 1px solid var(--primary-border);
    border-left: 3px solid var(--primary);
    padding: 1rem 1.1rem;
    background: var(--bg-muted);
    animation: fadeSlide 0.15s ease;
  }

  .wf-detail-header { font-size: 0.82rem; font-weight: 700; color: var(--text); margin-bottom: 0.35rem; }
  .wf-detail-desc   { font-size: 0.79rem; color: var(--text-muted); margin: 0 0 0.65rem 0; line-height: 1.5; }
  .wf-detail-items  { display: flex; flex-direction: column; gap: 0; }

  .wf-detail-item {
    display: grid;
    grid-template-columns: 140px 1fr;
    gap: 0.5rem;
    align-items: baseline;
    padding: 0.38rem 0;
    border-top: 1px solid var(--border);
    font-size: 0.78rem;
  }

  .wf-detail-item:first-child { border-top: none; }
  .wf-detail-item-name { font-weight: 600; color: var(--text); font-family: 'Courier New', monospace; font-size: 0.76rem; }
  .wf-detail-item-desc { color: var(--text-muted); line-height: 1.45; }

  .wf-inner {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    flex-wrap: wrap;
    padding: 0.5rem 0.75rem;
    background: var(--bg-muted);
    border: 1px solid var(--border);
    border-radius: 6px;
  }

  .wf-inner-label { font-size: 0.7rem; font-weight: 600; color: var(--text-muted); margin-right: 0.2rem; }
  .wf-inner-sep   { color: var(--text-faint); font-size: 0.72rem; }

  .wf-badge {
    font-size: 0.7rem;
    font-weight: 600;
    padding: 0.13rem 0.48rem;
    border-radius: 4px;
    border: 1px solid transparent;
  }

  .wf-badge-red    { background: var(--error-bg);   color: var(--error-text);   border-color: var(--error-border); }
  .wf-badge-blue   { background: var(--info-bg);    color: var(--info-text);    border-color: var(--info-border); }
  .wf-badge-green  { background: var(--success-bg); color: var(--success-text); border-color: var(--success-border); }
  .wf-badge-primary{ background: var(--primary-bg); color: var(--primary);      border-color: var(--primary-border); }
  .wf-badge-amber  { background: var(--warn-bg);    color: var(--warn-text);    border-color: var(--warn-border); }

  /* ── Feature Grid ── */
  .feat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 0.9rem;
  }

  .feat-card {
    border-radius: 8px;
    padding: 0.9rem 1rem 0.9rem 1.05rem;
    border: 1px solid var(--border);
    border-left-width: 3px;
    background: var(--bg-muted);
    text-align: left;
    cursor: pointer;
    font-family: inherit;
    width: 100%;
    transition: box-shadow 0.15s;
  }

  .feat-card:hover { box-shadow: 0 0 0 2px var(--border-strong); }
  .feat-card-open  { box-shadow: 0 0 0 2px var(--primary); }

  .feat-card-blue   { border-left-color: var(--primary); }
  .feat-card-green  { border-left-color: var(--success-text); }
  .feat-card-teal   { border-left-color: var(--info-text); }
  .feat-card-amber  { border-left-color: var(--warn-text); }
  .feat-card-red    { border-left-color: var(--error-text); }
  .feat-card-slate  { border-left-color: var(--border-strong); }

  .feat-card-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.5rem;
  }

  .feat-title { font-size: 0.82rem; font-weight: 700; color: var(--text); }
  .feat-toggle { font-size: 0.62rem; color: var(--text-faint); }

  .feat-list {
    margin: 0;
    padding-left: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .feat-list li { font-size: 0.78rem; color: var(--text-muted); line-height: 1.5; }

  /* Expanded spec section */
  .feat-specs {
    margin-top: 0.75rem;
    padding-top: 0.65rem;
    border-top: 1px solid var(--border);
    animation: fadeSlide 0.15s ease;
  }

  .feat-specs-title {
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-faint);
    margin-bottom: 0.4rem;
  }

  .feat-specs-grid {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.25rem 0.6rem;
    align-items: baseline;
  }

  .feat-spec-label {
    font-size: 0.72rem;
    color: var(--text-muted);
    font-weight: 500;
    white-space: nowrap;
  }

  .feat-spec-val {
    font-size: 0.72rem;
    color: var(--text);
    font-family: 'Courier New', monospace;
  }

  /* Shared animation */
  @keyframes fadeSlide {
    from { opacity: 0; transform: translateY(-4px); }
    to   { opacity: 1; transform: translateY(0); }
  }
</style>
