<script lang="ts">
  import '../app.css';
  import {
    getConfig, getModels, runTicketStream, listSessions, getSession,
    getKBStats, listKBDocs, searchKB,
    listConflicts, resolveConflict, correctChunk, listCorrections, chatStream,
    type RunResponse, type TicketSummary, type Task, type SessionSummary, type ModelOption,
    type KBDoc, type KBHit, type KBConflict, type KBStats, type KBCorrection,
    type ChatMessage,
  } from '$lib/api';
  import GuideTab from '$lib/components/GuideTab.svelte';
  import MCPTab from '$lib/components/MCPTab.svelte';
  import IterationTab from '$lib/components/IterationTab.svelte';
  import WikiTab from '$lib/components/WikiTab.svelte';
  import VendorDocTab from '$lib/components/VendorDocTab.svelte';

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

  function summaryTasks(s: TicketSummary): Task[] {
    return s.tasks ?? [];
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
      <WikiTab />
    {/if}

    <!-- ══════════════════════════ VENDOR DOCS TAB ══════════════════════════ -->
    {#if activeTab === 'vendordoc'}
      <VendorDocTab />
    {/if}

    <!-- ══════════════════════════════ MCP TAB ══════════════════════════════ -->
    {#if activeTab === 'mcp'}
      <MCPTab />
    {/if}

    <!-- ══════════════════════════ ITERATION TAB ══════════════════════════ -->
    {#if activeTab === 'iteration' && modules.iteration !== false}
      <IterationTab />
    {/if}

    {#if activeTab === 'guide'}
      <GuideTab />
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



</style>
