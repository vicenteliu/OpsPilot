<script lang="ts">
  // Guide tab — static, self-contained architecture/workflow/feature reference.
  // No API calls; owns all its own state and data.
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
      { key: 'kb',   accent: 'green', title: '知识管理',   items: ['LanceDB 向量知识库，支持 kb_search 工具调用', 'Wiki 页面管理，支持详情查看与 Markdown 下载', 'Vendor Docs 厂商文档库，SSE 流式解析', 'KB-augmented Chat，问答时自动检索知识'] },
      { key: 'mcp',  accent: 'teal',  title: 'MCP 集成',   items: ['JSON-RPC 2.0，支持 stdio 和 HTTP 两种传输', '工具前缀路由：mcp__fs__read_file', 'allowlist / denylist 工具过滤，全局审计开关', 'MCP tab 展示已注册服务器和工具列表'] },
      { key: 'eval', accent: 'amber', title: '评估与迭代', items: ['Golden Test Harness，多维度 evaluator 打分', 'Skill Lineage 版本树，支持 rollback 标记', 'OpenRouter / Gemini 两条 golden-test 管道', 'make golden-* 一键运行对比测试'] },
      { key: 'sec',  accent: 'red',   title: '安全与合规', items: ['PII 自动脱敏：邮箱、手机、IP、主机名等', '防二次脱敏：已有占位符不会被重复处理', 'MCP 配置禁止内联 secret，必须用环境变量', '全局 audit_every_call 审计开关'] },
      { key: 'ui',   accent: 'slate', title: '操作界面',   items: ['8 Tab WebUI：Run/Chat/KB/Wiki/VendorDoc/MCP/Iteration/Guide', 'REPL TUI，类 Claude Code 的终端交互体验', 'FastAPI REST + SSE，支持前后端分离部署', '暗色 / 亮色主题切换，响应式布局'] },
    ],
    en: [
      { key: 'ai',   accent: 'blue',  title: 'AI Capabilities',  items: ['Supports Anthropic Claude, Google Gemini, OpenRouter and more', 'ReAct reasoning loop, continues generation after tool calls', 'SSE streaming output, Run / Chat both support real-time responses', 'Session-level model and provider recording'] },
      { key: 'kb',   accent: 'green', title: 'Knowledge Mgmt',   items: ['LanceDB vector knowledge base, supports kb_search tool calls', 'Wiki page management with detail view and Markdown download', 'Vendor Docs library with SSE streaming parsing', 'KB-augmented Chat, auto-retrieves knowledge during QA'] },
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
        { name: 'LanceDB',      tech: '向量数据库',      desc: '存储文档 embedding，支持语义相似度检索，通过 kb_search 工具暴露给 LLM' },
        { name: 'SQLite + FTS5', tech: '关系型 + 全文索引', desc: 'Session 存储与 append-only 审计日志，FTS5 支持中文 ngram(2,3) 全文搜索' },
        { name: 'Playbooks',     tech: 'YAML 配置',       desc: 'Skill 定义：prompt 模板、provider 配置、evaluator 规则，版本化管理' },
      ]},
      en: { title: 'Storage — Local Embedded', desc: 'All embedded storage, zero ops overhead, git-friendly data files, fully offline-capable.', items: [
        { name: 'LanceDB',      tech: 'Vector DB',          desc: 'Stores document embeddings, semantic similarity retrieval, exposed to LLM via kb_search tool' },
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
        { name: 'KB Search', desc: 'LLM 决定调用 kb_search 时，LanceDB 语义检索最相关 top-k 文档片段注入 prompt' },
        { name: 'MCP Tools', desc: 'LLM 调用 mcp__<prefix>__<tool> 时，McpRegistry 路由到对应服务器执行并返回结果' },
        { name: 'LLM Call',  desc: '携带工具结果构建新 messages，发送给 Claude/Gemini/OpenRouter，获取下一步思考或最终输出' },
        { name: 'Evaluator', desc: '最终输出经多个 evaluator 打分，分数写入 session.score，高于阈值才视为成功' },
      ]},
      en: { title: 'Orchestrator — ReAct Loop', desc: 'Reasoning + Acting alternates; tool call results auto-injected into context until LLM outputs final JSON or max_turns is reached.', items: [
        { name: 'Redact',    desc: 'Apply redaction rules to ticket text; PII replaced with [REDACTED:type:hex], originals never enter LLM context' },
        { name: 'KB Search', desc: 'When LLM calls kb_search, LanceDB semantically retrieves top-k most relevant document chunks for prompt injection' },
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
      zh: { items: [{ label: '向量库', val: 'LanceDB (embedded)' }, { label: 'Embedding 模型', val: 'nomic-embed-text via Ollama' }, { label: '检索 top-k', val: '5（可配置）' }, { label: '文档格式', val: 'PDF / DOCX / MD / TXT via markitdown' }] },
      en: { items: [{ label: 'Vector DB', val: 'LanceDB (embedded)' }, { label: 'Embedding model', val: 'nomic-embed-text via Ollama' }, { label: 'Retrieval top-k', val: '5 (configurable)' }, { label: 'Document formats', val: 'PDF / DOCX / MD / TXT via markitdown' }] },
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
</script>

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
            <span class="arch-pill">LanceDB · vector KB</span>
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

<style>
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

  /* Animation (guide-only) */
  @keyframes fadeSlide {
    from { opacity: 0; transform: translateY(-4px); }
    to   { opacity: 1; transform: translateY(0); }
  }
</style>
